"""Shared CLI helpers for asa-ctrl commands."""

import sys
from typing import Optional

from asa_ctrl.common.constants import ExitCodes
from asa_ctrl.common.errors import (
    CorruptedModsDatabaseError,
    ModAlreadyEnabledError,
    RconAuthenticationError,
    RconConnectionError,
    RconPacketError,
    RconPasswordNotFoundError,
    RconPortNotFoundError,
    RconTimeoutError,
)


def exit_with_error(message: str, exit_code: int) -> None:
    """Print an error message and exit with the specified code."""
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(exit_code)


def map_exception_to_exit_code(exc: Exception) -> Optional[int]:
    """Translate known exceptions to asa-ctrl exit codes."""
    if isinstance(exc, RconPasswordNotFoundError):
        return ExitCodes.RCON_PASSWORD_NOT_FOUND
    if isinstance(exc, RconAuthenticationError):
        return ExitCodes.RCON_PASSWORD_WRONG
    if isinstance(exc, RconPortNotFoundError):
        return ExitCodes.RCON_CONNECTION_FAILED
    if isinstance(exc, RconConnectionError):
        return ExitCodes.RCON_CONNECTION_FAILED
    if isinstance(exc, RconTimeoutError):
        return ExitCodes.RCON_TIMEOUT
    if isinstance(exc, RconPacketError):
        return ExitCodes.RCON_PACKET_ERROR
    if isinstance(exc, ModAlreadyEnabledError):
        return ExitCodes.MOD_ALREADY_ENABLED
    if isinstance(exc, CorruptedModsDatabaseError):
        return ExitCodes.CORRUPTED_MODS_DATABASE
    return None
