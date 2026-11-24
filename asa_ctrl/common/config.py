"""Configuration parsing utilities for ASA Control.

`AsaSettings` is the seam between the process environment and the rest of the
package: every environment lookup that asa-ctrl performs goes through it, and
every question about the server's launch line is delegated to
`asa_ctrl.common.launch_config.LaunchConfiguration`.

Environment variable overrides for INI lookup paths:
    - `ASA_GAME_USER_SETTINGS_PATH`
    - `ASA_GAME_INI_PATH`
"""

import os
import configparser
from pathlib import Path
from typing import Optional, Dict, Mapping

from .constants import (
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ASA_CTRL_BIN,
    DEFAULT_LAUNCH_BASE,
    DEFAULT_MOD_DATABASE_PATH,
    DEFAULT_START_PARAMS,
    GAME_INI_PATH as DEFAULT_GAME_INI_PATH,
    GAME_USER_SETTINGS_PATH as DEFAULT_GAME_USER_SETTINGS_PATH,
)
from .errors import RconPasswordNotFoundError, RconPortNotFoundError
from .launch_config import LaunchConfiguration, coerce_bool


def parse_ini(file_path: str) -> Optional[configparser.ConfigParser]:
    """Parse an INI file, returning None when it is missing or unreadable.

    ARK writes duplicate keys into `GameUserSettings.ini`, so parsing is
    non-strict and the last value for a key wins.

    Args:
        file_path: Path to the INI file

    Returns:
        ConfigParser object, or None if the file is absent or cannot be parsed
    """
    if not Path(file_path).exists():
        return None

    config = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        config.read(file_path)
    except (OSError, configparser.Error):
        return None
    return config


class AsaSettings:
    """Resolve environment and INI-backed configuration for asa-ctrl."""

    def __init__(self, environ: Optional[Mapping[str, str]] = None) -> None:
        self._environ = environ if environ is not None else os.environ

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return self._environ.get(key, default)

    def start_params(self) -> Optional[str]:
        return self.get("ASA_START_PARAMS")

    def game_user_settings_path(self) -> str:
        return self.get("ASA_GAME_USER_SETTINGS_PATH", DEFAULT_GAME_USER_SETTINGS_PATH)  # type: ignore[arg-type]

    def game_ini_path(self) -> str:
        return self.get("ASA_GAME_INI_PATH", DEFAULT_GAME_INI_PATH)  # type: ignore[arg-type]

    def mod_database_path(self) -> str:
        return self.get("ASA_MOD_DATABASE_PATH", DEFAULT_MOD_DATABASE_PATH)  # type: ignore[arg-type]

    def asa_ctrl_bin(self) -> str:
        return self.get("ASA_CTRL_BIN", DEFAULT_ASA_CTRL_BIN)  # type: ignore[arg-type]

    def server_restart_cron(self) -> str:
        return self.get("SERVER_RESTART_CRON", "") or ""

    def server_restart_warnings(self) -> str:
        return self.get("SERVER_RESTART_WARNINGS", "") or ""

    def supervisor_pid_file(self) -> Optional[str]:
        return self.get("ASA_SUPERVISOR_PID_FILE")

    def server_pid_file(self) -> Optional[str]:
        return self.get("ASA_SERVER_PID_FILE")

    def get_server_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        config = parse_ini(self.game_user_settings_path())
        if not config or 'ServerSettings' not in config:
            return default
        return config['ServerSettings'].get(key, default)

    def launch_configuration(self) -> LaunchConfiguration:
        """Resolve the effective launch line for this environment.

        The legacy `ASA_START_PARAMS` string forms the base; discrete `ASA_*`
        variables are overlaid on top of it.
        """
        return LaunchConfiguration.from_env(self._environ)

    def get_start_param_value(self, key: str) -> Optional[str]:
        return self.launch_configuration().value(key)

    def rcon_launch_configuration(self) -> LaunchConfiguration:
        """Match the launch payload selected by the runtime for empty input."""
        config = self.launch_configuration()
        if config.is_empty():
            strict = coerce_bool(self.get("ASA_REQUIRE_ADMIN_PASSWORD"), False)
            return LaunchConfiguration.parse(DEFAULT_LAUNCH_BASE if strict else DEFAULT_START_PARAMS)
        return config

    def rcon_endpoint(self, config: Optional[LaunchConfiguration] = None) -> tuple[int, str]:
        """Resolve the managed server's port and password for local RCON calls."""
        if config is None:
            config = self.rcon_launch_configuration()
        raw_port = config.value("RCONPort") or self.get_server_setting("RCONPort") or "27020"
        try:
            port = int(raw_port)
        except ValueError:
            raise RconPortNotFoundError("RCONPort must be an integer from 1 to 65535.") from None
        if not 1 <= port <= 65535:
            raise RconPortNotFoundError("RCONPort must be an integer from 1 to 65535.")
        password = config.value("ServerAdminPassword") or self.get_server_setting("ServerAdminPassword")
        if not password:
            if coerce_bool(self.get("ASA_REQUIRE_ADMIN_PASSWORD"), False):
                raise RconPasswordNotFoundError("No server admin password configured in strict mode.")
            password = DEFAULT_ADMIN_PASSWORD
        return port, password

    def parse_start_params(self) -> Dict[str, str]:
        return self.launch_configuration().as_mapping()
