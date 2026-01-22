"""RCON command handling for the asa-ctrl CLI."""

from asa_ctrl.cli_helpers import exit_with_error
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

        except RconPasswordNotFoundError:
            exit_with_error(
                "Could not read RCON password. Make sure it is properly configured, either as "
                "start parameter ?ServerAdminPassword=mypass or in GameUserSettings.ini in the "
                "[ServerSettings] section as ServerAdminPassword=mypass",
                ExitCodes.RCON_PASSWORD_NOT_FOUND,
            )
        except RconAuthenticationError:
            exit_with_error(
                "Could not execute this RCON command. Authentication failed (wrong server password).",
                ExitCodes.RCON_PASSWORD_WRONG,
            )
        except RconPortNotFoundError:
            exit_with_error(
                "Could not find RCON port. Make sure it is properly configured in start parameters "
                "or GameUserSettings.ini",
                ExitCodes.RCON_CONNECTION_FAILED,
            )
        except RconConnectionError as e:
            exit_with_error(
                f"Failed to connect to RCON server: {e}",
                ExitCodes.RCON_CONNECTION_FAILED,
            )
        except RconTimeoutError as e:
            exit_with_error(
                f"RCON operation timed out: {e}",
                ExitCodes.RCON_TIMEOUT,
            )
        except RconPacketError as e:
            exit_with_error(
                f"RCON packet error: {e}",
                ExitCodes.RCON_PACKET_ERROR,
            )
        except ValueError as e:
            exit_with_error(
                f"Invalid command: {e}",
                ExitCodes.RCON_COMMAND_EXECUTION_FAILED,
            )
        except Exception as e:
            exit_with_error(
                f"Rcon command execution failed: {e}",
                ExitCodes.RCON_COMMAND_EXECUTION_FAILED,
            )
