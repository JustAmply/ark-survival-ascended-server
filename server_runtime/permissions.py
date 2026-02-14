"""Filesystem ownership normalization and privilege drop handling."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import shlex
from pathlib import Path
from typing import Optional

from .constants import (
    CLUSTER_DIR,
    PRIVS_DROPPED_ENV,
    SERVER_FILES_DIR,
    STEAMCMD_DIR,
    STEAM_HOME_DIR,
    TARGET_GID,
    TARGET_UID,
)


def _chown_if_possible(path: Path, recursive: bool) -> None:
    if recursive:
        for root, _, files in os.walk(path):
            shutil.chown(root, user=TARGET_UID, group=TARGET_GID)
            for name in files:
                shutil.chown(Path(root) / name, user=TARGET_UID, group=TARGET_GID)
    else:
        shutil.chown(path, user=TARGET_UID, group=TARGET_GID)


def ensure_permissions_and_drop_privileges(logger: logging.Logger) -> None:
    """Normalize ownership for persistent dirs and re-exec as gameserver."""
    if os.geteuid() != 0 or os.environ.get(PRIVS_DROPPED_ENV):
        return

    dirs = [Path(STEAM_HOME_DIR), Path(STEAMCMD_DIR), Path(SERVER_FILES_DIR), Path(CLUSTER_DIR)]
    for directory in dirs:
        directory.mkdir(parents=True, exist_ok=True)
        marker = directory / ".permissions_set"
        try:
            if not marker.exists():
                logger.info(
                    "Setting ownership recursively for %s to %s:%s (first run).",
                    directory,
                    TARGET_UID,
                    TARGET_GID,
                )
                _chown_if_possible(directory, recursive=True)
                marker.touch(exist_ok=True)
            _chown_if_possible(directory, recursive=False)
            if marker.exists():
                _chown_if_possible(marker, recursive=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to normalize permissions for %s: %s", directory, exc)

    os.environ[PRIVS_DROPPED_ENV] = "1"
    command = [sys.executable, "-m", "server_runtime"]
    exec_errors: list[str] = []
    if shutil.which("runuser"):
        try:
            os.execvp("runuser", ["runuser", "-u", "gameserver", "--"] + command)
        except OSError as exc:
            exec_errors.append(f"runuser: {exc}")
    if shutil.which("su"):
        try:
            os.execvp("su", ["su", "-s", "/bin/bash", "-c", shlex.join(command), "gameserver"])
        except OSError as exc:
            exec_errors.append(f"su: {exc}")

    if exec_errors:
        raise RuntimeError(
            "Failed to drop privileges via available helper(s): " + "; ".join(exec_errors)
        )

    raise RuntimeError("Neither runuser nor su is available for privilege drop")


def safe_kill_process(process: Optional[subprocess.Popen]) -> None:
    """Terminate a child process if running."""
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
