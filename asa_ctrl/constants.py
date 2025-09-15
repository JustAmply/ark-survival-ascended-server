"""
Constants and exit codes for ASA Control.
"""

class ExitCodes:
    """Exit codes for different error conditions."""
    OK = 0
    CORRUPTED_MODS_DATABASE = 1
    MOD_ALREADY_ENABLED = 2
    RCON_PASSWORD_NOT_FOUND = 3
    RCON_PASSWORD_WRONG = 4
    RCON_COMMAND_EXECUTION_FAILED = 5
    RESTART_SCHEDULE_INVALID = 6


class RconPacketTypes:
    """RCON packet type constants."""
    RESPONSE_VALUE = 0
    EXEC_COMMAND = 2
    AUTH_RESPONSE = 2
    AUTH = 3


# File paths
import os

DEFAULT_MOD_DATABASE_PATH = '/home/gameserver/server-files/mods.json'
DEFAULT_GAME_USER_SETTINGS_PATH = '/home/gameserver/server-files/ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini'
DEFAULT_GAME_INI_PATH = '/home/gameserver/server-files/ShooterGame/Saved/Config/WindowsServer/Game.ini'

MOD_DATABASE_PATH = os.environ.get('ASA_MOD_DATABASE_PATH', DEFAULT_MOD_DATABASE_PATH)
GAME_USER_SETTINGS_PATH = os.environ.get('ASA_GAME_USER_SETTINGS_PATH', DEFAULT_GAME_USER_SETTINGS_PATH)
GAME_INI_PATH = os.environ.get('ASA_GAME_INI_PATH', DEFAULT_GAME_INI_PATH)
