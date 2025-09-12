"""Configuration parsing utilities for ASA Control.

Enhancements in refactor:
* Added `parse_start_params` returning a structured mapping of key/values
* Added environment variable overrides for INI lookup paths:
    - `ASA_GAME_USER_SETTINGS_PATH`
    - `ASA_GAME_INI_PATH`
* Defensive parsing + minimal caching (can be expanded if needed)
"""

import os
import configparser
from pathlib import Path
from typing import Optional, Dict

from .constants import GAME_USER_SETTINGS_PATH as DEFAULT_GAME_USER_SETTINGS_PATH, GAME_INI_PATH as DEFAULT_GAME_INI_PATH

# Allow environment overrides (useful for tests / alternate layouts)
GAME_USER_SETTINGS_PATH = os.environ.get("ASA_GAME_USER_SETTINGS_PATH", DEFAULT_GAME_USER_SETTINGS_PATH)
GAME_INI_PATH = os.environ.get("ASA_GAME_INI_PATH", DEFAULT_GAME_INI_PATH)


class StartParamsHelper:
    """Helper for parsing start parameters from environment variables."""
    
    @staticmethod
    def get_value(start_params: Optional[str], key: str) -> Optional[str]:
        """
        Extract a parameter value from start parameters string.
        
        Args:
            start_params: The start parameters string
            key: The parameter key to find
            
        Returns:
            The parameter value or None if not found
        """
        if not start_params:
            return None
            
        key_pattern = f"{key}="
        offset = start_params.find(key_pattern)
        
        if offset == -1:
            return None
            
        offset += len(key_pattern)
        value = ""
        
        for char in start_params[offset:]:
            if char in [' ', '?']:
                break
            value += char
            
        return value


def parse_start_params(start_params: Optional[str]) -> Dict[str, str]:
    """Parse the raw `ASA_START_PARAMS` string into a dictionary.

    This is a best-effort parser: it looks for segments separated by `?` and
    key/value pairs separated by `=` (for the part preceding spaces / next `?`).

    Non key/value tokens (like the initial map) are stored under the synthetic
    key `_map` if detected.
    """
    result: Dict[str, str] = {}
    if not start_params:
        return result

    # Split on whitespace first to discard trailing flags (e.g. -WinLiveMaxPlayers=50)
    # We'll keep full string; then split tokens by space to treat flags separately.
    space_tokens = start_params.split()
    if not space_tokens:
        return result

    # First token often contains map plus ? delimited options
    first = space_tokens[0]
    parts = first.split('?')
    if parts:
        result['_map'] = parts[0]
        for seg in parts[1:]:
            if '=' in seg:
                k, v = seg.split('=', 1)
                result[k] = v

    # Remaining tokens may include -Key=Value style args
    for token in space_tokens[1:]:
        if token.startswith('-') and '=' in token:
            k, v = token[1:].split('=', 1)
            result[k] = v.strip('"')
    return result


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
            
        config = configparser.ConfigParser()
        config.read(file_path)
        return config
    
    @staticmethod
    def get_game_user_settings() -> Optional[configparser.ConfigParser]:
        """Get the GameUserSettings.ini configuration."""
        return IniConfigHelper.parse_ini(GAME_USER_SETTINGS_PATH)
    
    @staticmethod
    def get_game_ini() -> Optional[configparser.ConfigParser]:
        """Get the Game.ini configuration."""
        return IniConfigHelper.parse_ini(GAME_INI_PATH)
    
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