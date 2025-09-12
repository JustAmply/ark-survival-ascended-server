"""
Command Line Interface for ASA Control.

Provides CLI commands for RCON and mod management.
"""

import argparse
import sys
import os
from typing import List, Optional

from .constants import ExitCodes
from .rcon import execute_rcon_command
from .mods import ModDatabase, get_enabled_mod_ids
from .logging_config import configure_logging, get_logger
from .config import parse_start_params
from .errors import (
    RconPasswordNotFoundError, 
    RconAuthenticationError, 
    RconPortNotFoundError,
    ModAlreadyEnabledError,
    CorruptedModsDatabaseError
)


def exit_with_error(message: str, exit_code: int) -> None:
    """
    Print an error message and exit with the specified code.
    
    Args:
        message: The error message to print
        exit_code: The exit code to use
    """
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(exit_code)


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
                ExitCodes.RCON_PASSWORD_NOT_FOUND
            )
        except RconAuthenticationError:
            exit_with_error(
                "Could not execute this RCON command. Authentication failed (wrong server password).",
                ExitCodes.RCON_PASSWORD_WRONG
            )
        except RconPortNotFoundError:
            exit_with_error(
                "Could not find RCON port. Make sure it is properly configured in start parameters "
                "or GameUserSettings.ini",
                ExitCodes.RCON_PASSWORD_NOT_FOUND
            )
        except Exception as e:
            exit_with_error(
                f"Rcon command execution failed: {e}",
                ExitCodes.RCON_COMMAND_EXECUTION_FAILED
            )


class ModsCommand:
    """Handles mod management commands."""
    
    @staticmethod
    def add_parser(subparsers) -> None:
        """Add mods command parser to subparsers."""
        parser = subparsers.add_parser('mods', help='Interface for mod management')
        
        # Add subcommands for mods
        mod_subparsers = parser.add_subparsers(dest='mod_action', help='Mod actions')
        
        # Enable mod command
        enable_parser = mod_subparsers.add_parser('enable', help='Enable a mod')
        enable_parser.add_argument('mod_id', type=int, help='The mod ID to enable')
        
        # Disable mod command
        disable_parser = mod_subparsers.add_parser('disable', help='Disable a mod')
        disable_parser.add_argument('mod_id', type=int, help='The mod ID to disable')
        
        # List mods command
        list_parser = mod_subparsers.add_parser('list', help='List all mods')
        list_parser.add_argument('--enabled-only', action='store_true', 
                               help='Show only enabled mods')
        
        parser.set_defaults(func=ModsCommand.execute)
    
    @staticmethod
    def execute(args) -> None:
        """Execute a mod management command."""
        try:
            if args.mod_action == 'enable':
                ModsCommand._enable_mod(args.mod_id)
            elif args.mod_action == 'disable':
                ModsCommand._disable_mod(args.mod_id)
            elif args.mod_action == 'list':
                ModsCommand._list_mods(args.enabled_only)
            else:
                print("Please specify a mod action: enable, disable, or list")
                sys.exit(ExitCodes.OK)
                
        except CorruptedModsDatabaseError as e:
            exit_with_error(str(e), ExitCodes.CORRUPTED_MODS_DATABASE)
    
    @staticmethod
    def _enable_mod(mod_id: int) -> None:
        """Enable a mod."""
        try:
            db = ModDatabase.get_instance()
            db.enable_mod(mod_id)
            print(f"Enabled mod id '{mod_id}' successfully. The server will download the mod upon startup.")
            
        except ModAlreadyEnabledError:
            exit_with_error(
                "This mod is already enabled! Use 'asa-ctrl mods list' to see what mods are currently enabled.",
                ExitCodes.MOD_ALREADY_ENABLED
            )
    
    @staticmethod
    def _disable_mod(mod_id: int) -> None:
        """Disable a mod."""
        db = ModDatabase.get_instance()
        if db.disable_mod(mod_id):
            print(f"Disabled mod id '{mod_id}' successfully.")
        else:
            print(f"Mod id '{mod_id}' was not found in the database.")
    
    @staticmethod
    def _list_mods(enabled_only: bool = False) -> None:
        """List mods."""
        db = ModDatabase.get_instance()
        
        if enabled_only:
            mods = db.get_enabled_mods()
            print("Enabled mods:")
        else:
            mods = db.get_all_mods()
            print("All mods:")
        
        if not mods:
            print("  No mods found.")
            return
        
        for mod in mods:
            status = "enabled" if mod.enabled else "disabled"
            print(f"  {mod.mod_id}: {mod.name} ({status})")


def create_parser() -> argparse.ArgumentParser:
    """Create the main argument parser."""
    parser = argparse.ArgumentParser(
        prog='asa-ctrl',
        description='ARK: Survival Ascended Server Control Tool'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Add command parsers
    RconCommand.add_parser(subparsers)
    ModsCommand.add_parser(subparsers)
    
    return parser


def main(args: Optional[List[str]] = None) -> None:
    """
    Main entry point for the CLI.
    
    Args:
        args: Command line arguments (uses sys.argv if None)
    """
    # Configure logging early (idempotent)
    configure_logging()
    logger = get_logger(__name__)
    parser = create_parser()
    
    if args is None:
        args = sys.argv[1:]
    
    # If no arguments provided, show help
    if not args:
        parser.print_help()
        sys.exit(ExitCodes.OK)
    
    parsed_args = parser.parse_args(args)
    # Lazy debug output if user enabled verbose logging
    raw_params = os.environ.get('ASA_START_PARAMS')
    if raw_params and logger.isEnabledFor(10):  # DEBUG level
        logger.debug("Parsed start params: %s", parse_start_params(raw_params))
    
    # Execute the appropriate command
    if hasattr(parsed_args, 'func'):
        parsed_args.func(parsed_args)
    else:
        parser.print_help()
        sys.exit(ExitCodes.OK)


if __name__ == '__main__':
    main()