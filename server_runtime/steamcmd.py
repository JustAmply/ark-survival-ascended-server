"""SteamCMD installation and server update helpers."""

from __future__ import annotations

import logging
import subprocess
import tarfile
import urllib.request
from pathlib import Path

from .constants import SERVER_FILES_DIR, STEAM_APP_ID, STEAMCMD_DIR


def ensure_steamcmd(logger: logging.Logger) -> None:
    """Install SteamCMD when not present."""
    linux32_dir = Path(STEAMCMD_DIR) / "linux32"
    if linux32_dir.exists():
        return

    logger.info("Installing SteamCMD...")
    Path(STEAMCMD_DIR).mkdir(parents=True, exist_ok=True)
    archive_path = Path(STEAMCMD_DIR) / "steamcmd_linux.tar.gz"
    urllib.request.urlretrieve(
        "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz",
        archive_path,
    )
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(STEAMCMD_DIR)
    archive_path.unlink(missing_ok=True)


def update_server_files(logger: logging.Logger) -> None:
    """Run SteamCMD update/validate for ASA server files."""
    logger.info("Updating/validating ASA server files...")
    steamcmd = str(Path(STEAMCMD_DIR) / "steamcmd.sh")
    command = [
        steamcmd,
        "+force_install_dir",
        SERVER_FILES_DIR,
        "+login",
        "anonymous",
        "+app_update",
        STEAM_APP_ID,
        "validate",
        "+quit",
    ]
    subprocess.run(command, cwd=STEAMCMD_DIR, check=True)
