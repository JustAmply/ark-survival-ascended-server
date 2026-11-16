"""Read-only checks of known configuration and local filesystem access."""

import configparser
import os
from pathlib import Path

from asa_ctrl.common.config import AsaSettings
from asa_ctrl.common.constants import DEFAULT_ADMIN_PASSWORD, DEFAULT_LAUNCH_BASE, DEFAULT_START_PARAMS
from asa_ctrl.common.errors import AsaCtrlError
from asa_ctrl.common.launch_config import FALSE_VALUES, TRUE_VALUES, LaunchConfiguration
from asa_ctrl.core.restart_scheduler import CronSchedule, parse_warning_offsets
from server_runtime.constants import (
    SERVER_FILES_DIR, STEAMCMD_DIR, STEAM_HOME_DIR, VALIDATE_MODES,
    VALID_PROTON_PROFILES, VALID_TRANSLATOR_MODES, RuntimeSettings,
)


_RUNTIME_INTEGERS = {
    "SERVER_RESTART_DELAY": 0,
    "ASA_SHUTDOWN_SAVEWORLD_DELAY": 0,
    "ASA_SHUTDOWN_TIMEOUT": 1,
    "ASA_TRANSLATOR_PROBE_TIMEOUT": 1,
    "ASA_RESTART_MAX_FAILURES": 0,
    "ASA_RESTART_MAX_DELAY": 0,
}
_BOOLEANS = ("ENABLE_DEBUG", "ASA_RCON_ENABLED", "ASA_BATTLEYE", "ASA_REQUIRE_ADMIN_PASSWORD")
_BINARY_SWITCHES = ("PROTON_SKIP_CHECKSUM", "PROTON_SKIP_PREFLIGHT")
_RUNTIME_TEXT = (
    "ASA_VALIDATE", "ASA_UPDATE", "ASA_TRANSLATOR_MODE", "ASA_PROTON_PROFILE",
    "SERVER_RESTART_CRON", "SERVER_RESTART_WARNINGS", "ASA_LOG_LEVEL", "TZ",
)


def _launch_configuration(settings: AsaSettings, runtime: RuntimeSettings) -> LaunchConfiguration:
    config = settings.launch_configuration()
    if config.is_empty():
        # Match the launcher's legacy default, but never synthesize a password
        # in strict mode: that mode may instead use an explicit INI password.
        config = LaunchConfiguration.parse(
            DEFAULT_LAUNCH_BASE if runtime.require_admin_password else DEFAULT_START_PARAMS
        )
    return config


def check_configuration(settings: AsaSettings, *, filesystem: bool = False) -> dict:
    """Report errors and warnings without changing configuration or game data."""
    errors = []
    warnings = []
    source = {
        key: value for key in (*_RUNTIME_INTEGERS, *_BOOLEANS, *_BINARY_SWITCHES, *_RUNTIME_TEXT)
        if (value := settings.get(key)) is not None
    }
    runtime = RuntimeSettings.from_env(source)

    def integer(label, value, minimum, maximum=None):
        if value is None:
            return
        try:
            number = int(value)
            valid = number >= minimum and (maximum is None or number <= maximum)
        except ValueError:
            valid = False
        if not valid:
            bounds = f"{minimum}..{maximum}" if maximum is not None else f">= {minimum}"
            errors.append(f"{label} must be an integer {bounds}.")

    for key, minimum in _RUNTIME_INTEGERS.items():
        integer(key, source.get(key), minimum)
    for key in _BOOLEANS:
        if key in source and source[key].strip().lower() not in TRUE_VALUES | FALSE_VALUES:
            errors.append(f"{key} must be a boolean (1/0, true/false, yes/no, on/off).")
    for key in _BINARY_SWITCHES:
        if key in source and source[key] not in ("0", "1"):
            errors.append(f"{key} must be 0 or 1.")

    for key, value, choices in (
        ("ASA_VALIDATE", runtime.validate_mode, VALIDATE_MODES),
        ("ASA_UPDATE", runtime.update_mode, ("always", "startup", "manual")),
        ("ASA_TRANSLATOR_MODE", runtime.translator_mode, VALID_TRANSLATOR_MODES),
        ("ASA_PROTON_PROFILE", runtime.proton_profile, VALID_PROTON_PROFILES),
    ):
        if value not in choices:
            errors.append(f"{key} must be one of: {', '.join(choices)}.")
    if runtime.server_restart_cron:
        try:
            CronSchedule(runtime.server_restart_cron)
        except ValueError:
            errors.append("SERVER_RESTART_CRON must be a valid five-field cron expression.")
    if runtime.server_restart_warnings:
        try:
            parse_warning_offsets(runtime.server_restart_warnings)
        except ValueError:
            errors.append("SERVER_RESTART_WARNINGS must contain positive integer minutes separated by commas.")

    config = None
    try:
        config = _launch_configuration(settings, runtime)
        if not config.map_name:
            errors.append("The launch configuration must include a map name.")
        for key in ("Port", "RCONPort", "QueryPort"):
            integer(key, config.value(key) or settings.get_server_setting(key), 1, 65535)
        for key in ("WinLiveMaxPlayers", "MaxPlayers"):
            integer(key, config.value(key), 1)
        if config.value("Port") and config.value("Port") == config.value("QueryPort"):
            errors.append("Port and QueryPort must not share the same UDP port.")
        rcon = config.value("RCONEnabled") or settings.get_server_setting("RCONEnabled")
        if rcon is not None:
            if rcon.strip().lower() not in TRUE_VALUES | FALSE_VALUES:
                errors.append("RCONEnabled must be a boolean.")
            elif rcon.strip().lower() in FALSE_VALUES:
                warnings.append("RCON is disabled: shutdown saveworld and restart chat warnings cannot run.")
        if config.value("MaxPlayers") and config.value("WinLiveMaxPlayers"):
            if config.value("MaxPlayers") != config.value("WinLiveMaxPlayers"):
                warnings.append("MaxPlayers and WinLiveMaxPlayers disagree; use a single player limit.")
        password = config.value("ServerAdminPassword") or settings.get_server_setting("ServerAdminPassword")
        if not password and runtime.require_admin_password:
            errors.append("Strict password mode requires an explicitly configured admin password.")
        if not password or password == DEFAULT_ADMIN_PASSWORD:
            warnings.append("No non-default admin password is configured; set an explicit private password.")
    except (AsaCtrlError, OSError, ValueError, configparser.Error):
        # Exception text can contain secret-file contents or malformed INI values.
        errors.append("Cannot resolve launch configuration; check secret files and INI syntax/access.")

    if filesystem:
        paths = [
            ("server files", Path(SERVER_FILES_DIR)),
            ("SteamCMD", Path(STEAMCMD_DIR)),
            ("Proton storage", Path(STEAM_HOME_DIR)),
            ("mod database directory", Path(settings.mod_database_path()).parent),
        ]
        if config is not None and config.value("ClusterDirOverride"):
            paths.append(("cluster directory", Path(config.value("ClusterDirOverride"))))
        for label, path in paths:
            if not path.is_dir() or not os.access(path, os.R_OK | os.W_OK | os.X_OK):
                errors.append(f"The {label} must exist and be readable, writable and searchable by this user.")
        for label, path in (
            ("mod database", Path(settings.mod_database_path())),
            ("GameUserSettings.ini", Path(settings.game_user_settings_path())),
            ("Game.ini", Path(settings.game_ini_path())),
        ):
            if path.exists() and (not path.is_file() or not os.access(path, os.R_OK | os.W_OK)):
                errors.append(f"The {label} must be a readable and writable regular file.")
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def show_configuration(settings: AsaSettings) -> dict:
    """Expose known launch settings only; never print arbitrary extra values."""
    runtime = RuntimeSettings.from_env({
        "ASA_REQUIRE_ADMIN_PASSWORD": settings.get("ASA_REQUIRE_ADMIN_PASSWORD") or "",
    })
    config = _launch_configuration(settings, runtime)
    values = {"map": config.map_name}
    for key in (
        "Port", "RCONPort", "RCONEnabled", "WinLiveMaxPlayers", "MaxPlayers",
        "clusterid", "ClusterDirOverride", "mods",
    ):
        values[key] = config.value(key)
    for key in ("ServerAdminPassword", "ServerPassword", "SpectatorPassword"):
        values[key] = "<redacted>" if config.value(key) or settings.get_server_setting(key) else None
    return {"launch": values, "note": "Configured launch settings before runtime mod merging; extra values are omitted."}
