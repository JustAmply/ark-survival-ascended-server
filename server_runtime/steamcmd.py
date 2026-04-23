"""SteamCMD installation and server update helpers."""

from __future__ import annotations

import logging
import subprocess
import tarfile
import urllib.request
from pathlib import Path

from .archive_utils import safe_extract_tar
from .constants import (
    DEFAULT_PROTON_PROFILE,
    DEFAULT_TRANSLATOR_PROBE_TIMEOUT,
    SERVER_FILES_DIR,
    STEAM_APP_ID,
    STEAMCMD_DIR,
)
from .translation import (
    ExecutionContext,
    format_execution_error,
    run_probe_command,
    wrap_command,
)


def ensure_steamcmd(logger: logging.Logger) -> None:
    """Install SteamCMD when not present."""
    linux32_dir = Path(STEAMCMD_DIR) / "linux32"
    if linux32_dir.is_dir():
        return

    logger.info("Installing SteamCMD...")
    Path(STEAMCMD_DIR).mkdir(parents=True, exist_ok=True)
    archive_path = Path(STEAMCMD_DIR) / "steamcmd_linux.tar.gz"
    with urllib.request.urlopen(
        "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz",
        timeout=30,
    ) as response, archive_path.open("wb") as out_file:
        while True:
            chunk = response.read(8192)
            if not chunk:
                break
            out_file.write(chunk)
    with tarfile.open(archive_path, "r:gz") as tar:
        safe_extract_tar(tar, Path(STEAMCMD_DIR))
    archive_path.unlink(missing_ok=True)


def _steamcmd_script_path() -> Path:
    return Path(STEAMCMD_DIR) / "steamcmd.sh"


def _steamcmd_binary_path() -> Path:
    return Path(STEAMCMD_DIR) / "linux32" / "steamcmd"


def probe_steamcmd_translation(execution_context: ExecutionContext, logger: logging.Logger) -> None:
    """Run a quick SteamCMD probe through the translator on ARM64."""
    if not execution_context.translation_enabled:
        return

    steamcmd_binary = _steamcmd_binary_path()
    if not steamcmd_binary.is_file():
        raise RuntimeError(
            f"SteamCMD translation probe cannot run because '{steamcmd_binary}' is missing."
        )

    run_probe_command(
        execution_context,
        [str(steamcmd_binary), "+quit"],
        STEAMCMD_DIR,
        logger,
        "SteamCMD",
    )


def update_server_files(
    logger: logging.Logger,
    execution_context: ExecutionContext | None = None,
) -> None:
    """Run SteamCMD update/validate for ASA server files."""
    logger.info("Updating/validating ASA server files...")

    if execution_context and execution_context.translation_enabled:
        steamcmd_path = _steamcmd_binary_path()
    else:
        steamcmd_path = _steamcmd_script_path()

    command = [
        str(steamcmd_path),
        "+force_install_dir",
        SERVER_FILES_DIR,
        "+login",
        "anonymous",
        "+app_update",
        STEAM_APP_ID,
        "validate",
        "+quit",
    ]

    if execution_context:
        command = wrap_command(execution_context, command)

    try:
        subprocess.run(command, cwd=STEAMCMD_DIR, check=True)
    except OSError as exc:
        context = execution_context or ExecutionContext(
            architecture="unknown",
            translator_mode="none",
            runner_prefix=(),
            wraps_with_shell=False,
            probe_timeout=DEFAULT_TRANSLATOR_PROBE_TIMEOUT,
            proton_profile=DEFAULT_PROTON_PROFILE,
        )
        raise RuntimeError(format_execution_error("SteamCMD update", exc, context)) from exc
