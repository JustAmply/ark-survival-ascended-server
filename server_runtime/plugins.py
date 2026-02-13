"""Plugin loader detection and extraction for ASA API loader."""

from __future__ import annotations

import logging
import os
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
            dest_root = binary_dir.resolve()
            for member in zip_ref.infolist():
                member_target = (dest_root / member.filename).resolve()
                if member_target != dest_root and dest_root not in member_target.parents:
                    raise RuntimeError(f"Unsafe zip member path detected: {member.filename!r}")
                if member.is_dir() or member.filename.endswith("/"):
                    member_target.mkdir(parents=True, exist_ok=True)
                    continue
                member_target.parent.mkdir(parents=True, exist_ok=True)
                with zip_ref.open(member, "r") as source, member_target.open("wb") as dest:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        dest.write(chunk)
                perm = member.external_attr >> 16
                if perm:
                    try:
                        os.chmod(member_target, perm)
                    except OSError:
                        pass
        archive.unlink(missing_ok=True)

    plugin_binary = binary_dir / ASA_PLUGIN_BINARY_NAME
    if plugin_binary.exists():
        logger.info("Plugin loader detected; using %s", ASA_PLUGIN_BINARY_NAME)
        return ASA_PLUGIN_BINARY_NAME
    return ASA_BINARY_NAME
