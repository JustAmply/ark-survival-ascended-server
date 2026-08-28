"""Deep start-parameter normalization for the server launch contract."""

from __future__ import annotations

import logging
import os

from asa_ctrl.common.config import AsaSettings
from asa_ctrl.common.constants import DEFAULT_ADMIN_PASSWORD
from asa_ctrl.common.errors import CorruptedModsDatabaseError
from asa_ctrl.common.launch_config import LaunchConfiguration
from asa_ctrl.core.mods import get_enabled_mod_ids

from .constants import DEFAULT_START_PARAMS


def prepare_start_params(logger: logging.Logger) -> str:
    """Normalize the complete launch-parameter contract and export its result.

    The resolved launch line is written back to `ASA_START_PARAMS` so that child
    processes started by the supervisor - notably `asa-ctrl restart-scheduler` -
    observe exactly the line the server was launched with.
    """
    settings = AsaSettings()
    config = settings.launch_configuration()

    if config.is_empty():
        logger.warning(
            "No ASA_START_PARAMS provided; using default map payload with ServerAdminPassword."
        )
        config = LaunchConfiguration.parse(DEFAULT_START_PARAMS)
    else:
        _ensure_admin_password(config, settings, logger)

    _inject_dynamic_mods(config, settings, logger)
    config.ensure_flag("-nosteam")

    params = config.render()
    os.environ["ASA_START_PARAMS"] = params
    return params


def _ensure_admin_password(
    config: LaunchConfiguration, settings: AsaSettings, logger: logging.Logger
) -> None:
    if config.value("ServerAdminPassword"):
        return

    try:
        password_in_ini = bool(settings.get_server_setting("ServerAdminPassword"))
    except OSError as exc:
        logger.warning("Failed to read ServerAdminPassword from INI: %s", exc)
        password_in_ini = False

    if password_in_ini:
        return

    logger.warning(
        "ServerAdminPassword missing in ASA_START_PARAMS/INI; appending default fallback."
    )
    config.set_flag("ServerAdminPassword", DEFAULT_ADMIN_PASSWORD)


def _inject_dynamic_mods(
    config: LaunchConfiguration, settings: AsaSettings, logger: logging.Logger
) -> None:
    try:
        mod_ids = get_enabled_mod_ids(settings)
    except (CorruptedModsDatabaseError, OSError, ValueError) as exc:
        logger.warning("Failed to read dynamic mods; skipping mods injection: %s", exc)
        return

    if mod_ids:
        config.merge_mods(mod_ids)
