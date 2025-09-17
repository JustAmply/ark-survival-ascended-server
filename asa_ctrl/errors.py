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


class CorruptedModsDatabaseError(AsaCtrlError):
    """Raised when the mods database JSON file is corrupted."""
    pass


# Enterprise-specific errors
class ConfigValidationError(AsaCtrlError):
    """Configuration validation error."""
    pass


class SecurityViolationError(AsaCtrlError):
    """Security violation error."""
    pass


class HealthCheckError(AsaCtrlError):
    """Health check error."""
    pass
