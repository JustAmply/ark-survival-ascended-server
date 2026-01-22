"""RCON command handling for the asa-ctrl CLI."""

from asa_ctrl.cli_helpers import exit_with_error, map_exception_to_exit_code
from asa_ctrl.common.constants import ExitCodes
from asa_ctrl.common.errors import (
    RconAuthenticationError,
    RconConnectionError,
    RconPacketError,
    RconPasswordNotFoundError,
    RconPortNotFoundError,
    RconTimeoutError,
)
from asa_ctrl.core.rcon import execute_rcon_command


class RconCommand:
    """Handles RCON command execution."""

    @staticmethod
    def add_parser(subparsers) -> None:
        """Add RCON command parser to subparsers."""
        parser = subparsers.add_parser('rcon', help='Interface for RCON command execution')
        parser.add_argument('--exec', dest='command', required=True,
                            help='An RCON command to execute')
        parser.set_defaults(func=RconCommand.execute)

    @staticmethod
    def execute(args) -> None:
        """Execute an RCON command."""
        try:
            response = execute_rcon_command(args.command)
            print(response)

        except Exception as exc:
            exit_code = map_exception_to_exit_code(exc)
            if isinstance(exc, RconPasswordNotFoundError):
                message = (
                    "Could not read RCON password. Make sure it is properly configured, either as "
                    "start parameter ?ServerAdminPassword=mypass or in GameUserSettings.ini in the "
                    "[ServerSettings] section as ServerAdminPassword=mypass"
                )
            elif isinstance(exc, RconAuthenticationError):
                message = "Could not execute this RCON command. Authentication failed (wrong server password)."
            elif isinstance(exc, RconPortNotFoundError):
                message = (
                    "Could not find RCON port. Make sure it is properly configured in start parameters "
                    "or GameUserSettings.ini"
                )
            elif isinstance(exc, RconConnectionError):
                message = f"Failed to connect to RCON server: {exc}"
            elif isinstance(exc, RconTimeoutError):
                message = f"RCON operation timed out: {exc}"
            elif isinstance(exc, RconPacketError):
                message = f"RCON packet error: {exc}"
            elif isinstance(exc, ValueError):
                message = f"Invalid command: {exc}"
                exit_code = ExitCodes.RCON_COMMAND_EXECUTION_FAILED
            else:
                message = f"Rcon command execution failed: {exc}"
                exit_code = ExitCodes.RCON_COMMAND_EXECUTION_FAILED

            if exit_code is None:
                exit_code = ExitCodes.RCON_COMMAND_EXECUTION_FAILED

            exit_with_error(message, exit_code)
