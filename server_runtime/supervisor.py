"""Process supervision and startup orchestration runtime."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from .bootstrap import configure_timezone, ensure_machine_id, maybe_debug_hold
from .constants import (
    ASA_BINARY_DIR,
    ASA_COMPAT_DATA,
    ASA_CTRL_BIN,
    EARLY_CRASH_THRESHOLD_SECONDS,
    LOG_DIR,
    PID_FILE,
    STEAM_HOME_DIR,
    SUPERVISOR_PID_FILE,
    RuntimeSettings,
)
from .logging_utils import configure_runtime_logging
from .params import ensure_nosteam_flag, ensure_server_admin_password, inject_mods_param
from .permissions import ensure_permissions_and_drop_privileges, safe_kill_process
from .plugins import resolve_launch_binary
from .proton import (
    build_launch_command,
    build_launch_environment,
    ensure_proton_compat_data,
    install_proton_if_needed,
    resolve_proton_version,
)
from .shutdown import send_saveworld, signal_name, stop_server_process
from .steamcmd import ensure_steamcmd, probe_steamcmd_translation, update_server_files
from .translation import format_execution_error, resolve_execution_context


class ServerSupervisor:
    """Container-level supervisor for server runtime."""

    def __init__(self, settings: RuntimeSettings, logger: logging.Logger) -> None:
        self.settings = settings
        self.logger = logger
        self.server_process: Optional[subprocess.Popen] = None
        self.log_streamer_process: Optional[subprocess.Popen] = None
        self.restart_scheduler_process: Optional[subprocess.Popen] = None
        self.shutdown_in_progress = False
        self.supervisor_exit_requested = False
        self.restart_requested = False
        self.execution_context = resolve_execution_context(logger)
        self.safe_profile_retry_used = self.execution_context.proton_profile == "safe"
        self.quick_crash_count = 0
        self.last_run_duration = 0.0

    def register_supervisor_pid(self) -> None:
        Path(SUPERVISOR_PID_FILE).write_text(f"{os.getpid()}\n", encoding="utf-8")

    def start_restart_scheduler(self) -> None:
        cron = (os.environ.get("SERVER_RESTART_CRON") or "").strip()
        if not cron:
            return
        if not os.path.isfile(ASA_CTRL_BIN):
            self.logger.warning(
                "Restart scheduler requested but asa-ctrl path '%s' is not a regular file.",
                ASA_CTRL_BIN,
            )
            return
        if not os.access(ASA_CTRL_BIN, os.X_OK):
            self.logger.warning(
                "Restart scheduler requested but asa-ctrl binary '%s' is not executable.",
                ASA_CTRL_BIN,
            )
            return
        if self.restart_scheduler_process and self.restart_scheduler_process.poll() is None:
            return

        warnings = (os.environ.get("SERVER_RESTART_WARNINGS") or "").strip()
        os.environ["SERVER_RESTART_WARNINGS"] = warnings or "30,5,1"
        os.environ["ASA_SUPERVISOR_PID_FILE"] = SUPERVISOR_PID_FILE
        os.environ["ASA_SERVER_PID_FILE"] = PID_FILE
        self.restart_scheduler_process = subprocess.Popen([ASA_CTRL_BIN, "restart-scheduler"])
        self.logger.info(
            "Started restart scheduler (PID %s) with cron '%s'.",
            self.restart_scheduler_process.pid,
            cron,
        )

    def _prepare_runtime_env(self) -> None:
        uid = os.getuid()
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        if runtime_dir:
            p = Path(runtime_dir)
            if not p.is_dir() or not os.access(runtime_dir, os.W_OK):
                runtime_dir = f"/tmp/xdg-runtime-{uid}"
        else:
            candidate = f"/run/user/{uid}"
            if Path(candidate).exists() and os.access(candidate, os.W_OK):
                runtime_dir = candidate
            else:
                runtime_dir = f"/tmp/xdg-runtime-{uid}"
        Path(runtime_dir).mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(runtime_dir, 0o700)
        except OSError:
            pass

        os.environ["XDG_RUNTIME_DIR"] = runtime_dir
        os.environ["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = STEAM_HOME_DIR
        os.environ["STEAM_COMPAT_DATA_PATH"] = ASA_COMPAT_DATA
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        os.environ.setdefault("XDG_SESSION_TYPE", "headless")

    def _start_log_streamer(self) -> None:
        log_dir = Path(LOG_DIR)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "ShooterGame.log"
        log_file.touch(exist_ok=True)
        if self.log_streamer_process and self.log_streamer_process.poll() is None:
            return
        self.log_streamer_process = subprocess.Popen(
            ["tail", "-n", "0", "-F", str(log_file)],
            stdout=sys.stdout,
            stderr=subprocess.DEVNULL,
        )

    def _launch_server_once(self) -> int:
        probe_steamcmd_translation(self.execution_context, self.logger)
        update_server_files(self.logger, self.execution_context)
        params = ensure_server_admin_password(self.logger)
        version = resolve_proton_version(self.logger)
        proton_dir_name = install_proton_if_needed(version, self.logger)
        ensure_proton_compat_data(proton_dir_name, self.logger)
        params = inject_mods_param(params, self.logger)
        params = ensure_nosteam_flag(params)
        self._prepare_runtime_env()
        launch_binary = resolve_launch_binary(self.logger)
        self._start_log_streamer()

        self.logger.info("Starting ASA dedicated server.")
        self.logger.info("Start parameters: %s", params)
        self.logger.info(
            "Launch context: translator=%s, proton_profile=%s",
            self.execution_context.translator_mode,
            self.execution_context.proton_profile,
        )
        command = build_launch_command(
            proton_dir_name,
            launch_binary,
            params,
            self.execution_context,
        )
        launch_env = build_launch_environment(dict(os.environ), self.execution_context.proton_profile)
        start_time = time.monotonic()
        try:
            self.server_process = subprocess.Popen(command, cwd=ASA_BINARY_DIR, env=launch_env)
        except OSError as exc:
            raise RuntimeError(format_execution_error("Proton launch", exc, self.execution_context)) from exc

        Path(PID_FILE).write_text(f"{self.server_process.pid}\n", encoding="utf-8")
        exit_code = self.server_process.wait()
        self.last_run_duration = max(0.0, time.monotonic() - start_time)
        return exit_code

    def _perform_shutdown_sequence(self, sig: int, purpose: str) -> None:
        if self.shutdown_in_progress:
            self.logger.info("Signal %s received but shutdown already in progress.", signal_name(sig))
            return
        self.shutdown_in_progress = True
        self.logger.info(
            "Received signal %s for %s; initiating graceful shutdown.",
            signal_name(sig),
            purpose,
        )

        if self.server_process is None or self.server_process.poll() is not None:
            self.logger.info("Shutdown requested before launch or after stop; no server process to stop.")
            return

        saveworld_sent = send_saveworld(self.logger)
        if saveworld_sent:
            time.sleep(max(self.settings.shutdown_saveworld_delay, 0))
        stop_server_process(self.server_process, self.settings.shutdown_timeout, self.logger)

    def _handle_shutdown_signal(self, sig: int, _frame) -> None:
        self.supervisor_exit_requested = True
        self._perform_shutdown_sequence(sig, "container shutdown")

    def _handle_restart_signal(self, sig: int, _frame) -> None:
        self.restart_requested = True
        self._perform_shutdown_sequence(sig, "scheduled restart")

    def _apply_early_crash_policy(self, exit_code: int) -> int | None:
        if self.last_run_duration >= EARLY_CRASH_THRESHOLD_SECONDS:
            self.quick_crash_count = 0
            return None

        if self.execution_context.proton_profile == "safe":
            self.logger.error(
                "Server exited after %.1fs while ASA_PROTON_PROFILE=safe. "
                "Failing fast to avoid an endless restart loop.",
                self.last_run_duration,
            )
            return exit_code if exit_code != 0 else 1

        self.quick_crash_count += 1
        self.logger.warning(
            "Early server exit detected after %.1fs (%s/2) with ASA_PROTON_PROFILE=%s.",
            self.last_run_duration,
            self.quick_crash_count,
            self.execution_context.proton_profile,
        )

        if self.quick_crash_count >= 2 and not self.safe_profile_retry_used:
            self.execution_context.proton_profile = "safe"
            self.safe_profile_retry_used = True
            self.quick_crash_count = 0
            os.environ["ASA_PROTON_PROFILE"] = "safe"
            self.logger.warning(
                "Switching ASA_PROTON_PROFILE to 'safe' after repeated early crashes."
            )
        return None

    def _cleanup_after_run(self) -> None:
        safe_kill_process(self.server_process)
        Path(PID_FILE).unlink(missing_ok=True)
        self.server_process = None

    def cleanup(self) -> None:
        safe_kill_process(self.server_process)
        safe_kill_process(self.log_streamer_process)
        safe_kill_process(self.restart_scheduler_process)
        Path(PID_FILE).unlink(missing_ok=True)
        Path(SUPERVISOR_PID_FILE).unlink(missing_ok=True)

    def run(self) -> int:
        signal.signal(signal.SIGTERM, self._handle_shutdown_signal)
        signal.signal(signal.SIGINT, self._handle_shutdown_signal)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, self._handle_shutdown_signal)
        if hasattr(signal, "SIGUSR1"):
            signal.signal(signal.SIGUSR1, self._handle_restart_signal)

        while True:
            exit_code = 1
            try:
                exit_code = self._launch_server_once()
                self.logger.info(
                    "Server process exited with code %s after %.1fs.",
                    exit_code,
                    self.last_run_duration,
                )
            except Exception:
                self.last_run_duration = 0.0
                self.logger.exception("Unhandled exception during server run; will attempt restart.")
            finally:
                self._cleanup_after_run()

            if self.supervisor_exit_requested:
                self.logger.info("Supervisor exit requested; terminating with code %s.", exit_code)
                return exit_code

            if self.restart_requested:
                self.logger.info(
                    "Scheduled restart completed; relaunching after %ss.",
                    self.settings.server_restart_delay,
                )
                self.quick_crash_count = 0
            else:
                fail_fast_code = self._apply_early_crash_policy(exit_code)
                if fail_fast_code is not None:
                    return fail_fast_code

                self.logger.info(
                    "Server exited unexpectedly with code %s; restarting after %ss.",
                    exit_code,
                    self.settings.server_restart_delay,
                )

            self.restart_requested = False
            self.shutdown_in_progress = False
            time.sleep(max(self.settings.server_restart_delay, 0))


def main() -> None:
    logger = configure_runtime_logging()
    settings = RuntimeSettings.from_env()

    if os.geteuid() == 0:
        configure_timezone(logger)
        ensure_machine_id(logger)
    maybe_debug_hold(settings.enable_debug, logger)
    ensure_permissions_and_drop_privileges(logger)

    ensure_steamcmd(logger)

    supervisor = ServerSupervisor(settings, logger)
    supervisor.register_supervisor_pid()
    supervisor.start_restart_scheduler()

    try:
        code = supervisor.run()
    finally:
        supervisor.cleanup()
    raise SystemExit(code)
