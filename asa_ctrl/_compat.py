"""Deprecated names, kept importable for programmatic users.

Everything here is a pass-through to the module that owns the behaviour. These
names are resolved lazily by `asa_ctrl.__getattr__`, which raises a
`DeprecationWarning` naming the replacement, so the live modules carry no
compatibility surface of their own.

Nothing inside this package imports from here. When the deprecation period is
over, delete this module and the corresponding entries in `asa_ctrl.__all__`.
"""

from __future__ import annotations

import configparser
from typing import Dict, Optional

from .common.config import AsaSettings, parse_ini
from .common.launch_config import LaunchConfiguration


class StartParamsHelper:
    """Deprecated. Use `asa_ctrl.common.launch_config.LaunchConfiguration`."""

    @staticmethod
    def get_value(start_params: Optional[str], key: str) -> Optional[str]:
        return LaunchConfiguration.parse(start_params).value(key)


class IniConfigHelper:
    """Deprecated. Use `asa_ctrl.common.config.parse_ini` or `AsaSettings`."""

    @staticmethod
    def parse_ini(file_path: str) -> Optional[configparser.ConfigParser]:
        return parse_ini(file_path)

    @staticmethod
    def get_game_user_settings() -> Optional[configparser.ConfigParser]:
        return parse_ini(AsaSettings().game_user_settings_path())

    @staticmethod
    def get_game_ini() -> Optional[configparser.ConfigParser]:
        return parse_ini(AsaSettings().game_ini_path())

    @staticmethod
    def get_server_setting(key: str, default: Optional[str] = None) -> Optional[str]:
        return AsaSettings().get_server_setting(key, default)


def parse_start_params(start_params: Optional[str]) -> Dict[str, str]:
    """Deprecated. Use `LaunchConfiguration.parse(...).as_mapping()`."""
    return LaunchConfiguration.parse(start_params).as_mapping()
