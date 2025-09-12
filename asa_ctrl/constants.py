"""Constants and exit codes for ASA Control.

This module also defines default file system paths which can be overridden via
environment variables. This provides better testability and container
customisation without changing code inside the image.

Environment overrides:
* ``ASA_MOD_DATABASE_PATH`` – path to ``mods.json``
* ``ASA_GAME_USER_SETTINGS_PATH`` – path to ``GameUserSettings.ini``
* ``ASA_GAME_INI_PATH`` – path to ``Game.ini``
"""

from __future__ import annotations

import os

class ExitCodes:
    """Exit codes for different error conditions."""
    OK = 0
    CORRUPTED_MODS_DATABASE = 1
    MOD_ALREADY_ENABLED = 2
    RCON_PASSWORD_NOT_FOUND = 3
    RCON_PASSWORD_WRONG = 4
    RCON_COMMAND_EXECUTION_FAILED = 5


class RconPacketTypes:
    """RCON packet type constants."""
    RESPONSE_VALUE = 0
    EXEC_COMMAND = 2
    AUTH_RESPONSE = 2
    AUTH = 3


# File paths (overridable via environment for tests / custom layouts)
MOD_DATABASE_PATH = os.environ.get('ASA_MOD_DATABASE_PATH', '/home/gameserver/server-files/mods.json')
GAME_USER_SETTINGS_PATH = os.environ.get(
    'ASA_GAME_USER_SETTINGS_PATH',
    '/home/gameserver/server-files/ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini'
)
GAME_INI_PATH = os.environ.get(
    'ASA_GAME_INI_PATH',
    '/home/gameserver/server-files/ShooterGame/Saved/Config/WindowsServer/Game.ini'
)