"""SteamCMD installation and server update helpers."""

from __future__ import annotations

import logging
import subprocess
import tarfile
import urllib.request
from pathlib import Path
from typing import Optional

from .archive_utils import safe_extract_archive
from .constants import (
    ASA_BINARY_DIR,
    ASA_BINARY_NAME,
    SERVER_FILES_DIR,
    STEAM_APP_ID,
    STEAMCMD_DIR,
    VALIDATE_ALWAYS,
    VALIDATE_MODES,
    VALIDATE_NEVER,
    RuntimeSettings,
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
        safe_extract_archive(tar, Path(STEAMCMD_DIR))
    archive_path.unlink(missing_ok=True)


def server_is_installed() -> bool:
    """Whether a previous SteamCMD run already produced the server executable."""
    return (Path(ASA_BINARY_DIR) / ASA_BINARY_NAME).is_file()


def should_validate(settings: RuntimeSettings, logger: logging.Logger) -> bool:
    """Decide whether this update run checksums every installed file.

    ``validate`` re-reads the whole installation, so on the supervisor's restart
    loop it would add minutes of downtime to every relaunch. The default only
    pays that cost for the initial install, where a truncated download is a real
    risk; afterwards a plain ``app_update`` still picks up new builds.
    """
    mode = settings.validate_mode_or_default()
    if settings.validate_mode != mode:
        logger.warning(
            "Invalid ASA_VALIDATE %r; falling back to %r. Valid values: %s.",
            settings.validate_mode,
            mode,
            ", ".join(VALIDATE_MODES),
        )

    if mode == VALIDATE_ALWAYS:
        return True
    if mode == VALIDATE_NEVER:
        return False
    return not server_is_installed()


def update_server_files(
    logger: logging.Logger, settings: Optional[RuntimeSettings] = None
) -> None:
    """Run SteamCMD update (optionally with validation) for ASA server files."""
    settings = settings or RuntimeSettings.from_env()
    validate = should_validate(settings, logger)

    if validate:
        logger.info("Updating and validating ASA server files...")
    else:
        logger.info("Updating ASA server files (skipping checksum validation).")

    steamcmd = str(Path(STEAMCMD_DIR) / "steamcmd.sh")
    command = [
        steamcmd,
        "+force_install_dir",
        SERVER_FILES_DIR,
        "+login",
        "anonymous",
        "+app_update",
        STEAM_APP_ID,
    ]
    if validate:
        command.append("validate")
    command.append("+quit")
    subprocess.run(command, cwd=STEAMCMD_DIR, check=True)
