"""
Custom exception classes for ASA Control.
"""


class AsaCtrlError(Exception):
    """Base exception class for ASA Control errors."""
    pass


class ModAlreadyEnabledError(AsaCtrlError):
    """Raised when trying to enable a mod that is already enabled."""
    pass


class RconPasswordNotFoundError(AsaCtrlError):
    """Raised when RCON password cannot be found in configuration."""
    pass


class RconPortNotFoundError(AsaCtrlError):
    """Raised when RCON port cannot be found in configuration."""
    pass


class RconAuthenticationError(AsaCtrlError):
    """Raised when RCON authentication fails."""
    pass


class RconConnectionError(AsaCtrlError):
    """Raised when RCON connection fails."""
    pass


class RconPacketError(AsaCtrlError):
    """Raised when RCON packet is malformed or invalid."""
    pass


class RconTimeoutError(AsaCtrlError):
    """Raised when RCON operation times out."""
    pass


class CorruptedModsDatabaseError(AsaCtrlError):
    """Raised when the mods database JSON file is corrupted."""
    pass
