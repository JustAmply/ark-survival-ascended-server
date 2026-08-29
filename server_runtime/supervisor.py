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

from asa_ctrl.common.config import AsaSettings
from asa_ctrl.common.errors import AsaCtrlError
from asa_ctrl.core.rcon import execute_rcon_command

from .bootstrap import configure_timezone, ensure_machine_id, maybe_debug_hold
from .constants import (
    ASA_BINARY_DIR,
    ASA_CTRL_BIN,
    LOG_DIR,
    PID_FILE,
    STEAM_COMPAT_DIR,
    SUPERVISOR_PID_FILE,
    RuntimeSettings,
)
from .launch_env import LaunchEnvironment
from .logging_utils import configure_runtime_logging
from .params import prepare_start_params
from .permissions import ensure_permissions_and_drop_privileges
from .plugins import resolve_launch_binary
from .proton import ProtonSelection, ensure_proton_compat_data, prepare_proton
from .steamcmd import ensure_steamcmd, update_server_files
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

    def _build_launch_command(self, proton_dir_name: str, launch_binary: str, params: str) -> list[str]:
        proton_path = str(Path(STEAM_COMPAT_DIR) / proton_dir_name / "proton")
        # launch_binary is intentionally a filename; process cwd is ASA_BINARY_DIR.
        command = [proton_path, "run", launch_binary]
        if params.strip():
            command.extend(shlex.split(params))
        return command

    def _launch_server_once(self) -> int:
        update_server_files(self.logger, self.settings)
        params = prepare_start_params(self.logger)
        self.proton = prepare_proton(self.logger, self.settings, self.proton)
        proton_dir_name = self.proton.directory_name
        ensure_proton_compat_data(proton_dir_name, self.logger)
        self.server_env = LaunchEnvironment.from_process(self.settings).for_server(params)
        # The server inherits the raised limit, which is what esync needs.
        configure_wine_sync(self.logger)
        launch_binary = resolve_launch_binary(self.logger)
        self._start_log_streamer()

        self.logger.info("Starting ASA dedicated server.")
        self.logger.info("Start parameters: %s", params)
        command = self._build_launch_command(proton_dir_name, launch_binary, params)
        self.server_process = subprocess.Popen(command, cwd=ASA_BINARY_DIR, env=self.server_env)
        Path(PID_FILE).write_text(f"{self.server_process.pid}\n", encoding="utf-8")
        return self.server_process.wait()

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
            try:
                exit_code = self._launch_server_once()
                self.logger.info("Server process exited with code %s.", exit_code)
            except Exception:
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
