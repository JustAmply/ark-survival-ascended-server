"""
Configuration parsing utilities for ASA Control.

Handles parsing of INI files and start parameters.
"""

import os
import configparser
from pathlib import Path
from typing import Optional, Dict, Any

from .constants import GAME_USER_SETTINGS_PATH, GAME_INI_PATH


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