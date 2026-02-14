"""Start parameter normalization helpers."""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path

from .constants import ASA_CTRL_BIN, DEFAULT_START_PARAMS, GAME_USER_SETTINGS_PATH


def has_server_admin_password_in_params(params: str) -> bool:
    return "ServerAdminPassword=" in params


def server_admin_password_in_ini() -> bool:
    path = Path(GAME_USER_SETTINGS_PATH)
    if not path.exists():
        return False
    pattern = re.compile(r"^[ \t]*ServerAdminPassword[ \t]*=")
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if pattern.search(line):
                return True
    except OSError:
        return False
    return False


def ensure_server_admin_password(logger: logging.Logger) -> str:
    """Ensure launch params include/admin password fallback behavior."""
    params = (os.environ.get("ASA_START_PARAMS") or "").strip()
    if has_server_admin_password_in_params(params) or server_admin_password_in_ini():
        return params

    if params:
        logger.warning(
            "ServerAdminPassword missing in ASA_START_PARAMS/INI; appending default fallback."
        )
        params = f"{params} -ServerAdminPassword=changeme"
    else:
        logger.warning(
            "No ASA_START_PARAMS provided; using default map payload with ServerAdminPassword."
        )
        params = DEFAULT_START_PARAMS

    os.environ["ASA_START_PARAMS"] = params
    return params


def inject_mods_param(base_params: str, logger: logging.Logger) -> str:
    """Append dynamic mods string from asa-ctrl if present."""
    try:
        result = subprocess.run(
            [ASA_CTRL_BIN, "mods-string"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        logger.warning("Failed to query dynamic mods via asa-ctrl: %s", exc)
        return base_params

    mods = (result.stdout or "").strip()
    if not mods:
        return base_params
    merged = f"{base_params} {mods}".strip()
    os.environ["ASA_START_PARAMS"] = merged
    return merged


def ensure_nosteam_flag(params: str) -> str:
    """Ensure -nosteam exists in start params exactly once."""
    tokens = params.split()
    if any(token == "-nosteam" for token in tokens):
        return params
    updated = f"{params} -nosteam".strip()
    os.environ["ASA_START_PARAMS"] = updated
    return updated
