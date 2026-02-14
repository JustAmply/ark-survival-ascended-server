"""Constants and settings helpers for the standalone server runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass


TARGET_UID = 25000
TARGET_GID = 25000
STEAM_APP_ID = "2430930"

STEAMCMD_DIR = "/home/gameserver/steamcmd"
SERVER_FILES_DIR = "/home/gameserver/server-files"
STEAM_HOME_DIR = "/home/gameserver/Steam"
CLUSTER_DIR = "/home/gameserver/cluster-shared"
ASA_BINARY_DIR = f"{SERVER_FILES_DIR}/ShooterGame/Binaries/Win64"
LOG_DIR = f"{SERVER_FILES_DIR}/ShooterGame/Saved/Logs"
GAME_USER_SETTINGS_PATH = (
    f"{SERVER_FILES_DIR}/ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini"
)
STEAM_COMPAT_DATA = f"{SERVER_FILES_DIR}/steamapps/compatdata"
ASA_COMPAT_DATA = f"{STEAM_COMPAT_DATA}/{STEAM_APP_ID}"
STEAM_COMPAT_DIR = f"{STEAM_HOME_DIR}/compatibilitytools.d"

ASA_BINARY_NAME = "ArkAscendedServer.exe"
ASA_PLUGIN_BINARY_NAME = "AsaApiLoader.exe"
FALLBACK_PROTON_VERSION = "8-21"
DEFAULT_START_PARAMS = (
    "TheIsland_WP?listen?Port=7777?RCONPort=27020?RCONEnabled=True?"
    "ServerAdminPassword=changeme"
)

PID_FILE = "/home/gameserver/.asa-server.pid"
SUPERVISOR_PID_FILE = "/home/gameserver/.asa-supervisor.pid"
ASA_CTRL_BIN = "/usr/local/bin/asa-ctrl"
PRIVS_DROPPED_ENV = "START_SERVER_PRIVS_DROPPED"

PROTON_REPO = "GloriousEggroll/proton-ge-custom"


def env_bool(key: str, default: bool = False) -> bool:
    value = os.environ.get(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(key: str, default: int) -> int:
    value = os.environ.get(key)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass
class RuntimeSettings:
    """Typed runtime settings sourced from the environment."""

    enable_debug: bool
    server_restart_delay: int
    shutdown_saveworld_delay: int
    shutdown_timeout: int

    @classmethod
    def from_env(cls) -> "RuntimeSettings":
        return cls(
            enable_debug=env_bool("ENABLE_DEBUG", False),
            server_restart_delay=env_int("SERVER_RESTART_DELAY", 15),
            shutdown_saveworld_delay=env_int("ASA_SHUTDOWN_SAVEWORLD_DELAY", 15),
            shutdown_timeout=env_int("ASA_SHUTDOWN_TIMEOUT", 180),
        )
