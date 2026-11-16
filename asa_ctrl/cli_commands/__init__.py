"""Registry for CLI subcommands."""

from .mods_command import ModsCommand
from .rcon_command import RconCommand
from .restart_scheduler_command import RestartSchedulerCommand
from .status_command import StatusCommand
from .config_command import ConfigCommand

COMMANDS = (
    RconCommand,
    ModsCommand,
    RestartSchedulerCommand,
    StatusCommand,
    ConfigCommand,
)

__all__ = ["COMMANDS", "RconCommand", "ModsCommand", "RestartSchedulerCommand", "StatusCommand", "ConfigCommand"]
