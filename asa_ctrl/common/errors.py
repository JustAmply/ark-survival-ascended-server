"""
Custom exception classes for ASA Control.
"""


class AsaCtrlError(Exception):
    """Base exception class for ASA Control errors."""
    pass


class ConfigurationError(AsaCtrlError, ValueError):
    """Raised when configuration cannot safely produce a server launch."""


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


class RconDeliveryUnknownError(AsaCtrlError):
    """The command may have reached the server but no reply confirmed it."""


class RconUnconfirmedTimeoutError(RconTimeoutError, RconDeliveryUnknownError):
    """Timed out after beginning command delivery."""


class RconUnconfirmedConnectionError(RconConnectionError, RconDeliveryUnknownError):
    """Lost the connection after beginning command delivery."""


class RconUnconfirmedPacketError(RconPacketError, RconDeliveryUnknownError):
    """Could not match a valid reply to the command."""


class CorruptedModsDatabaseError(AsaCtrlError):
    """Raised when the mods database JSON file is corrupted."""
    pass
