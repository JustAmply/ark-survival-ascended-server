"""Constants and settings helpers for the standalone server runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

from asa_ctrl.common.constants import (
    DEFAULT_LAUNCH_BASE,  # noqa: F401  (re-exported for runtime consumers)
    DEFAULT_START_PARAMS,  # noqa: F401  (re-exported for runtime consumers)
)
from asa_ctrl.common.launch_config import coerce_bool, coerce_int


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
FALLBACK_PROTON_VERSION = "10-34"

PID_FILE = "/home/gameserver/.asa-server.pid"
SUPERVISOR_PID_FILE = "/home/gameserver/.asa-supervisor.pid"
ASA_CTRL_BIN = "/usr/local/bin/asa-ctrl"
PRIVS_DROPPED_ENV = "START_SERVER_PRIVS_DROPPED"

PROTON_REPO = "GloriousEggroll/proton-ge-custom"


def env_bool(key: str, default: bool = False) -> bool:
    """Read a boolean runtime switch from the process environment."""
    return coerce_bool(os.environ.get(key), default)


def env_int(key: str, default: int) -> int:
    """Read an integer runtime setting from the process environment."""
    return coerce_int(os.environ.get(key), default)


DEFAULT_RESTART_WARNINGS = "30,5,1"


@dataclass
class RuntimeSettings:
    """Typed runtime settings sourced from the environment.

    This is the container's configuration contract in one place: every runtime
    switch the image understands (bar the launch line itself, which
    `LaunchConfiguration` owns) is a field here, so the modules that act on them
    can be driven from a plain mapping in tests.
    """

    enable_debug: bool
    server_restart_cron: str
    server_restart_warnings: str
    server_restart_delay: int
    shutdown_saveworld_delay: int
    shutdown_timeout: int
    proton_version: str
    proton_skip_checksum: bool
    log_level: str
    timezone: str

    @classmethod
    def from_env(cls, environ: Optional[Mapping[str, str]] = None) -> "RuntimeSettings":
        source: Mapping[str, str] = os.environ if environ is None else environ

        def text(key: str, default: str = "") -> str:
            return (source.get(key) or default).strip()

        return cls(
            enable_debug=coerce_bool(source.get("ENABLE_DEBUG"), False),
            server_restart_cron=text("SERVER_RESTART_CRON"),
            server_restart_warnings=text("SERVER_RESTART_WARNINGS"),
            server_restart_delay=coerce_int(source.get("SERVER_RESTART_DELAY"), 15),
            shutdown_saveworld_delay=coerce_int(
                source.get("ASA_SHUTDOWN_SAVEWORLD_DELAY"), 15
            ),
            shutdown_timeout=coerce_int(source.get("ASA_SHUTDOWN_TIMEOUT"), 180),
            proton_version=text("PROTON_VERSION"),
            proton_skip_checksum=source.get("PROTON_SKIP_CHECKSUM") == "1",
            log_level=text("ASA_LOG_LEVEL", "INFO").upper(),
            timezone=text("TZ"),
        )

    def restart_warnings_or_default(self) -> str:
        """Warning cadence for the restart scheduler, never empty."""
        return self.server_restart_warnings or DEFAULT_RESTART_WARNINGS
