"""Plugin loader detection and extraction for ASA API loader."""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from .constants import ASA_BINARY_DIR, ASA_BINARY_NAME, ASA_PLUGIN_BINARY_NAME


def resolve_launch_binary(logger: logging.Logger) -> str:
    """Extract AsaApi zip when present and choose launch executable."""
    binary_dir = Path(ASA_BINARY_DIR)
    archives = sorted(binary_dir.glob("AsaApi_*.zip"))
    for archive in archives:
        logger.info("Extracting plugin loader archive %s", archive.name)
        with zipfile.ZipFile(archive, "r") as zip_ref:
            zip_ref.extractall(binary_dir)
        archive.unlink(missing_ok=True)

    plugin_binary = binary_dir / ASA_PLUGIN_BINARY_NAME
    if plugin_binary.exists():
        logger.info("Plugin loader detected; using %s", ASA_PLUGIN_BINARY_NAME)
        return ASA_PLUGIN_BINARY_NAME
    return ASA_BINARY_NAME
