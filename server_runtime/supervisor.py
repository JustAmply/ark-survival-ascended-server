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

from asa_ctrl.common.config import AsaSettings
from asa_ctrl.common.errors import AsaCtrlError
from asa_ctrl.common.launch_config import LaunchConfiguration
from asa_ctrl.core.rcon import execute_rcon_command

from .bootstrap import configure_timezone, ensure_machine_id, maybe_debug_hold
from .constants import (
    ASA_BINARY_DIR,
    ASA_CTRL_BIN,
    EARLY_CRASH_THRESHOLD_SECONDS,
    LOG_DIR,
    PID_FILE,
    SUPERVISOR_PID_FILE,
    RuntimeSettings,
)
from .launch_env import LaunchEnvironment, resolve_proton_profile
from .logging_utils import configure_runtime_logging
from .params import prepare_start_params
from .permissions import ensure_permissions_and_drop_privileges
from .plugins import resolve_launch_binary
from .proton import (
    ProtonSelection,
    build_launch_command,
    ensure_proton_compat_data,
    prepare_proton,
)
from .steamcmd import ensure_steamcmd, probe_steamcmd_translation, update_server_files
from .translation import format_execution_error, resolve_execution_context
from .wine_sync import configure_wine_sync


class ServerSupervisor:
    """Container-level supervisor for server runtime."""

    def __init__(self, settings: RuntimeSettings, logger: logging.Logger) -> None:
        self.settings = settings
        self.logger = logger
        self.server_process: Optional[subprocess.Popen] = None
        self.log_streamer_process: Optional[subprocess.Popen] = None
        self.restart_scheduler_process: Optional[subprocess.Popen] = None
        # Carried across relaunches so the loop resolves Proton once, not once
        # per restart.
        self.proton: Optional[ProtonSelection] = None
        # The environment the running server was launched with; RCON discovery
        # during shutdown reads the same values the server itself received.
        self.server_env: Optional[dict[str, str]] = None
        self.shutdown_in_progress = False
        self.supervisor_exit_requested = False
        self.restart_requested = False
        self.execution_context = resolve_execution_context(logger, settings)
        self.proton_profile = resolve_proton_profile(settings.proton_profile, logger)
        self.logger.info("Effective Proton profile: %s", self.proton_profile)
        self.translator_probe_complete = False
        self.quick_crash_count = 0
        self.last_run_duration = 0.0

    def register_supervisor_pid(self) -> None:
        Path(SUPERVISOR_PID_FILE).write_text(f"{os.getpid()}\n", encoding="utf-8")

    def start_restart_scheduler(self) -> None:
        cron = self.settings.server_restart_cron
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

        # The scheduler reads its own configuration from the environment, so it
        # is handed one built for it rather than the supervisor's own.
        scheduler_env = LaunchEnvironment.from_process(self.settings).for_scheduler()
        self.restart_scheduler_process = subprocess.Popen(
            [ASA_CTRL_BIN, "restart-scheduler"], env=scheduler_env
        )
        self.logger.info(
            "Started restart scheduler (PID %s) with cron '%s'.",
            self.restart_scheduler_process.pid,
            cron,
        )

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
        started = time.monotonic()
        if self.execution_context.translation_enabled and not self.translator_probe_complete:
            probe_steamcmd_translation(self.execution_context, self.logger)
            self.translator_probe_complete = True
        update_server_files(self.logger, self.settings, execution_context=self.execution_context)
        self.logger.info("Server file update completed in %.1fs.", time.monotonic() - started)
        params = prepare_start_params(self.logger)
        started = time.monotonic()
        self.proton = prepare_proton(
            self.logger, self.settings, self.proton, execution_context=self.execution_context
        )
        proton_dir_name = self.proton.directory_name
        ensure_proton_compat_data(proton_dir_name, self.logger)
        self.logger.info("Proton preparation completed in %.1fs.", time.monotonic() - started)
        self.server_env = LaunchEnvironment.from_process(self.settings).for_server(
            params, proton_profile=self.proton_profile
        )
        # The server inherits the raised limit, which is what esync needs.
        configure_wine_sync(self.logger, self.server_env)
        launch_binary = resolve_launch_binary(self.logger)
        self._start_log_streamer()

        self.logger.info("Starting ASA dedicated server.")
        self.logger.info("Start parameters: %s", LaunchConfiguration.parse(params).render_for_logging())
        command = self._build_launch_command(proton_dir_name, launch_binary, params)
        start_time = time.monotonic()
        try:
            self.server_process = subprocess.Popen(command, cwd=ASA_BINARY_DIR, env=self.server_env)
        except OSError as exc:
            raise RuntimeError(format_execution_error("Proton launch", exc, self.execution_context)) from exc
        Path(PID_FILE).write_text(f"{self.server_process.pid}\n", encoding="utf-8")
        exit_code = self.server_process.wait()
        self.last_run_duration = max(0.0, time.monotonic() - start_time)
        return exit_code

    def _perform_shutdown_sequence(self, sig: int, purpose: str) -> None:
        if self.shutdown_in_progress:
            self.logger.info("Signal %s received but shutdown already in progress.", self._signal_name(sig))
            return
        self.shutdown_in_progress = True
        self.logger.info(
            "Received signal %s for %s; initiating graceful shutdown.",
            self._signal_name(sig),
            purpose,
        )

        if self.server_process is None or self.server_process.poll() is not None:
            self.logger.info("Shutdown requested before launch or after stop; no server process to stop.")
            return

        saveworld_sent = self._send_saveworld()
        if saveworld_sent:
            time.sleep(max(self.settings.shutdown_saveworld_delay, 0))
        self._stop_server_process(self.server_process)

    def _rcon_settings(self) -> Optional[AsaSettings]:
        """Discover RCON from the environment the running server was given.

        Falls back to the process environment when no server has been launched
        yet, which is what the shutdown path sees on an early signal.
        """
        if self.server_env is None:
            return None
        return AsaSettings(self.server_env)

    def _send_saveworld(self) -> bool:
        try:
            execute_rcon_command("saveworld", settings=self._rcon_settings())
            ok = True
        except (AsaCtrlError, ValueError) as exc:
            self.logger.debug("saveworld RCON failure: %s", exc)
            ok = False

        if ok:
            self.logger.info("saveworld command sent successfully.")
        else:
            self.logger.warning("Failed to execute saveworld command via RCON.")
        return ok

    def _stop_server_process(self, process: Optional[subprocess.Popen]) -> None:
        if process is None or process.poll() is not None:
            self.logger.info("Server process already stopped.")
            return

        self.logger.info("Sending SIGTERM to server process PID %s", process.pid)
        process.terminate()
        timeout = self.settings.shutdown_timeout
        deadline = time.time() + max(timeout, 1)
        while process.poll() is None and time.time() < deadline:
            time.sleep(1)

        if process.poll() is None:
            self.logger.warning(
                "Server did not stop within %ss; sending SIGKILL to PID %s",
                timeout,
                process.pid,
            )
            process.kill()

    @staticmethod
    def _signal_name(sig: int) -> str:
        try:
            return signal.Signals(sig).name
        except ValueError:
            return str(sig)

    @staticmethod
    def _terminate_process(process: Optional[subprocess.Popen]) -> None:
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

    def _handle_shutdown_signal(self, sig: int, _frame) -> None:
        self.supervisor_exit_requested = True
        self._perform_shutdown_sequence(sig, "container shutdown")

    def _handle_restart_signal(self, sig: int, _frame) -> None:
        self.restart_requested = True
        self._perform_shutdown_sequence(sig, "scheduled restart")

    def _build_launch_command(self, proton_dir_name: str, launch_binary: str, params: str) -> list[str]:
        return build_launch_command(
            proton_dir_name, launch_binary, params, self.execution_context
        )

    def _apply_early_crash_policy(self, exit_code: int) -> int | None:
        # The experimental stability policy must not change native restart behavior.
        if not self.execution_context.translation_enabled:
            return None
        if self.last_run_duration >= EARLY_CRASH_THRESHOLD_SECONDS:
            self.quick_crash_count = 0
            return None

        if self.proton_profile == "safe":
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
            self.proton_profile,
        )

        if self.quick_crash_count >= 2:
            self.proton_profile = "safe"
            self.quick_crash_count = 0
            self.logger.warning(
                "Switching ASA_PROTON_PROFILE to 'safe' after repeated early crashes."
            )
        return None

    def _cleanup_after_run(self) -> None:
        self._terminate_process(self.server_process)
        Path(PID_FILE).unlink(missing_ok=True)
        self.server_process = None

    def cleanup(self) -> None:
        self._terminate_process(self.server_process)
        self._terminate_process(self.log_streamer_process)
        self._terminate_process(self.restart_scheduler_process)
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
            server_ran = False
            try:
                exit_code = self._launch_server_once()
                server_ran = True
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
                fail_fast_code = self._apply_early_crash_policy(exit_code) if server_ran else None
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
    settings = RuntimeSettings.from_env()
    logger = configure_runtime_logging(settings)

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
