"""Registry for CLI subcommands."""

from .mods_command import ModsCommand
from .rcon_command import RconCommand
from .restart_scheduler_command import RestartSchedulerCommand

COMMANDS = (
    RconCommand,
    ModsCommand,
    RestartSchedulerCommand,
)

__all__ = ["COMMANDS", "RconCommand", "ModsCommand", "RestartSchedulerCommand"]
