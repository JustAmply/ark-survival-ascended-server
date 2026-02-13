"""Process supervision and startup orchestration runtime."""

from __future__ import annotations

import logging
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from .bootstrap import configure_timezone, maybe_debug_hold
from .constants import (
    ASA_BINARY_DIR,
    ASA_COMPAT_DATA,
    ASA_CTRL_BIN,
    LOG_DIR,
    PID_FILE,
    STEAM_COMPAT_DIR,
    SUPERVISOR_PID_FILE,
    RuntimeSettings,
)
from .logging_utils import configure_runtime_logging
from .params import ensure_nosteam_flag, ensure_server_admin_password, inject_mods_param
from .permissions import ensure_permissions_and_drop_privileges, safe_kill_process
from .plugins import resolve_launch_binary
from .proton import ensure_proton_compat_data, install_proton_if_needed, resolve_proton_version
from .shutdown import send_saveworld, signal_name, stop_server_process
from .steamcmd import ensure_steamcmd, update_server_files


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

        os.environ["SERVER_RESTART_WARNINGS"] = os.environ.get("SERVER_RESTART_WARNINGS", "30,5,1")
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
            if not p.exists() or not os.access(runtime_dir, os.W_OK):
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
        os.environ["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = "/home/gameserver/Steam"
        os.environ["STEAM_COMPAT_DATA_PATH"] = ASA_COMPAT_DATA

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

    def _build_launch_command(self, proton_dir_name: str, launch_binary: str, params: str) -> list[str]:
        proton_path = str(Path(STEAM_COMPAT_DIR) / proton_dir_name / "proton")
        command = [proton_path, "run", launch_binary]
        if params.strip():
            command.extend(shlex.split(params))
        return command

    def _launch_server_once(self) -> int:
        update_server_files(self.logger)
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
        command = self._build_launch_command(proton_dir_name, launch_binary, params)
        self.server_process = subprocess.Popen(command, cwd=ASA_BINARY_DIR)
        Path(PID_FILE).write_text(f"{self.server_process.pid}\n", encoding="utf-8")
        return self.server_process.wait()

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

        send_saveworld(self.logger)
        time.sleep(max(self.settings.shutdown_saveworld_delay, 0))
        stop_server_process(self.server_process, self.settings.shutdown_timeout, self.logger)

    def _handle_shutdown_signal(self, sig: int, _frame) -> None:
        self.supervisor_exit_requested = True
        self._perform_shutdown_sequence(sig, "container shutdown")

    def _handle_restart_signal(self, sig: int, _frame) -> None:
        self.restart_requested = True
        self._perform_shutdown_sequence(sig, "scheduled restart")

    def _cleanup_after_run(self) -> None:
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
        signal.signal(signal.SIGHUP, self._handle_shutdown_signal)
        if hasattr(signal, "SIGUSR1"):
            signal.signal(signal.SIGUSR1, self._handle_restart_signal)

        while True:
            exit_code = 1
            try:
                exit_code = self._launch_server_once()
                self.logger.info("Server process exited with code %s.", exit_code)
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
            else:
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
