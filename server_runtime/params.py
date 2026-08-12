"""Deep start-parameter normalization for the server launch contract."""

from __future__ import annotations

import logging
import os

from asa_ctrl.common.config import AsaSettings
from asa_ctrl.common.errors import CorruptedModsDatabaseError
from asa_ctrl.core.mods import format_mod_list_for_server

from .constants import DEFAULT_START_PARAMS


def prepare_start_params(logger: logging.Logger) -> str:
    """Normalize the complete launch-parameter contract and export its result."""
    settings = AsaSettings()
    params = (settings.start_params() or "").strip()

    if not settings.get_start_param_value("ServerAdminPassword"):
        try:
            password_in_ini = bool(settings.get_server_setting("ServerAdminPassword"))
        except OSError as exc:
            logger.warning("Failed to read ServerAdminPassword from INI: %s", exc)
            password_in_ini = False

        if not password_in_ini:
            params = _add_default_admin_password(params, logger)

    try:
        mods = format_mod_list_for_server(settings)
    except (CorruptedModsDatabaseError, OSError, ValueError) as exc:
        logger.warning("Failed to read dynamic mods; skipping mods injection: %s", exc)
    else:
        if mods:
            params = f"{params} {mods}".strip()

    params = _add_nosteam_flag(params)
    os.environ["ASA_START_PARAMS"] = params
    return params


def _add_default_admin_password(params: str, logger: logging.Logger) -> str:
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
    return params


def _add_nosteam_flag(params: str) -> str:
    tokens = params.split()
    if any(token == "-nosteam" for token in tokens):
        return params
    return f"{params} -nosteam".strip()
