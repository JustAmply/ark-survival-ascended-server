"""
Constants and exit codes for ASA Control.
"""

import os

class ExitCodes:
    """Exit codes for different error conditions."""
    OK = 0
    CORRUPTED_MODS_DATABASE = 1
    MOD_ALREADY_ENABLED = 2
    RCON_PASSWORD_NOT_FOUND = 3
    RCON_PASSWORD_WRONG = 4
    RCON_COMMAND_EXECUTION_FAILED = 5
    # Enterprise-specific exit codes
    CONFIG_VALIDATION_ERROR = 10
    SECURITY_VIOLATION = 11
    API_AUTHENTICATION_FAILED = 12
    RESOURCE_LIMIT_EXCEEDED = 13
    HEALTH_CHECK_FAILED = 14


class RconPacketTypes:
    """RCON packet type constants."""
    RESPONSE_VALUE = 0
    EXEC_COMMAND = 2
    AUTH_RESPONSE = 2
    AUTH = 3


# File paths with environment variable overrides for enterprise configuration management
MOD_DATABASE_PATH = os.environ.get('ASA_MOD_DATABASE_PATH', '/home/gameserver/server-files/mods.json')
GAME_USER_SETTINGS_PATH = os.environ.get('ASA_GAME_USER_SETTINGS_PATH', '/home/gameserver/server-files/ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini')
GAME_INI_PATH = os.environ.get('ASA_GAME_INI_PATH', '/home/gameserver/server-files/ShooterGame/Saved/Config/WindowsServer/Game.ini')

# Enterprise configuration paths
CONFIG_DIR = os.environ.get('ASA_CONFIG_DIR', '/home/gameserver/config')
AUDIT_LOG_PATH = os.environ.get('ASA_AUDIT_LOG_PATH', '/home/gameserver/logs/audit.log')
METRICS_PATH = os.environ.get('ASA_METRICS_PATH', '/home/gameserver/metrics')
BACKUP_DIR = os.environ.get('ASA_BACKUP_DIR', '/home/gameserver/backups')
