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
    DEFAULT_ASA_CTRL_BIN,
    DEFAULT_MOD_DATABASE_PATH,
    GAME_INI_PATH as DEFAULT_GAME_INI_PATH,
    GAME_USER_SETTINGS_PATH as DEFAULT_GAME_USER_SETTINGS_PATH,
)
from .launch_config import LaunchConfiguration


def get_game_user_settings_path() -> str:
    """Resolve the GameUserSettings.ini path with env overrides."""
    return os.environ.get("ASA_GAME_USER_SETTINGS_PATH", DEFAULT_GAME_USER_SETTINGS_PATH)


def get_game_ini_path() -> str:
    """Resolve the Game.ini path with env overrides."""
    return os.environ.get("ASA_GAME_INI_PATH", DEFAULT_GAME_INI_PATH)


class IniConfigHelper:
    """Helper for parsing INI configuration files."""
    
    @staticmethod
    def parse_ini(file_path: str) -> Optional[configparser.ConfigParser]:
        """
        Parse an INI file and return a ConfigParser object.
        
        Args:
            file_path: Path to the INI file
            
        Returns:
            ConfigParser object or None if file doesn't exist
        """
        if not Path(file_path).exists():
            return None
            
        config = configparser.ConfigParser(strict=False)
        try:
            config.read(file_path)
        except (OSError, configparser.Error):
            return None
        return config
    
    @staticmethod
    def get_game_user_settings() -> Optional[configparser.ConfigParser]:
        """Get the GameUserSettings.ini configuration."""
        return IniConfigHelper.parse_ini(get_game_user_settings_path())
    
    @staticmethod
    def get_game_ini() -> Optional[configparser.ConfigParser]:
        """Get the Game.ini configuration."""
        return IniConfigHelper.parse_ini(get_game_ini_path())
    
    @staticmethod
    def get_server_setting(key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Get a server setting from GameUserSettings.ini.
        
        Args:
            key: The setting key to retrieve
            default: Default value if setting not found
            
        Returns:
            The setting value or default
        """
        config = IniConfigHelper.get_game_user_settings()
        if not config or 'ServerSettings' not in config:
            return default
            
        return config['ServerSettings'].get(key, default)


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
        config = IniConfigHelper.parse_ini(self.game_user_settings_path())
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

    def parse_start_params(self) -> Dict[str, str]:
        return self.launch_configuration().as_mapping()

    @staticmethod
    def _get_start_param_value(start_params: Optional[str], key: str) -> Optional[str]:
        return LaunchConfiguration.parse(start_params).value(key)

    @staticmethod
    def _parse_start_params(start_params: Optional[str]) -> Dict[str, str]:
        return LaunchConfiguration.parse(start_params).as_mapping()


class StartParamsHelper:
    """Compatibility wrapper for start parameter parsing."""

    @staticmethod
    def get_value(start_params: Optional[str], key: str) -> Optional[str]:
        return LaunchConfiguration.parse(start_params).value(key)


def parse_start_params(start_params: Optional[str]) -> Dict[str, str]:
    """Compatibility wrapper for start parameter parsing."""
    return LaunchConfiguration.parse(start_params).as_mapping()
