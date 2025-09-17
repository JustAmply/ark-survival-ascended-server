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
    RCON_CONNECTION_FAILED = 6
    RCON_PACKET_ERROR = 7
    RCON_TIMEOUT = 8


class RconPacketTypes:
    """RCON packet type constants."""
    RESPONSE_VALUE = 0
    EXEC_COMMAND = 2
    AUTH_RESPONSE = 2
    AUTH = 3


# File paths
MOD_DATABASE_PATH = '/home/gameserver/server-files/mods.json'
GAME_USER_SETTINGS_PATH = '/home/gameserver/server-files/ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini'
GAME_INI_PATH = '/home/gameserver/server-files/ShooterGame/Saved/Config/WindowsServer/Game.ini'
