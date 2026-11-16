"""Registry for CLI subcommands."""

from .mods_command import ModsCommand
from .rcon_command import RconCommand
from .restart_scheduler_command import RestartSchedulerCommand
from .status_command import StatusCommand

COMMANDS = (
    RconCommand,
    ModsCommand,
    RestartSchedulerCommand,
    StatusCommand,
)

__all__ = ["COMMANDS", "RconCommand", "ModsCommand", "RestartSchedulerCommand", "StatusCommand"]
