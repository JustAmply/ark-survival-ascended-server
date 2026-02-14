"""Graceful shutdown orchestration for ASA runtime."""

from __future__ import annotations

import logging
import signal
import subprocess
import time
from typing import Optional

from .constants import ASA_CTRL_BIN


def send_saveworld(logger: logging.Logger) -> bool:
    """Try issuing saveworld via asa-ctrl rcon."""
    try:
        result = subprocess.run(
            [ASA_CTRL_BIN, "rcon", "--exec", "saveworld"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ok = result.returncode == 0
    except OSError:
        ok = False

    if ok:
        logger.info("saveworld command sent successfully.")
    else:
        logger.warning("Failed to execute saveworld command via RCON.")
    return ok


def stop_server_process(
    server_process: Optional[subprocess.Popen],
    shutdown_timeout: int,
    logger: logging.Logger,
) -> None:
    """Gracefully stop server process, then force kill on timeout."""
    if server_process is None or server_process.poll() is not None:
        logger.info("Server process already stopped.")
        return

    logger.info("Sending SIGTERM to server process PID %s", server_process.pid)
    server_process.terminate()
    deadline = time.time() + max(shutdown_timeout, 1)
    while server_process.poll() is None and time.time() < deadline:
        time.sleep(1)

    if server_process.poll() is None:
        logger.warning(
            "Server did not stop within %ss; sending SIGKILL to PID %s",
            shutdown_timeout,
            server_process.pid,
        )
        server_process.kill()


def signal_name(sig: int) -> str:
    """Best effort signal name for logging."""
    try:
        return signal.Signals(sig).name
    except ValueError:
        return str(sig)
