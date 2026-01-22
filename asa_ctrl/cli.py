"""Command Line Interface for ASA Control."""

import argparse
import sys
from typing import List, Optional

from .common.config import AsaSettings
from .common.logging_config import configure_logging, get_logger
from .common.constants import ExitCodes
from .cli_commands import COMMANDS


def create_parser() -> argparse.ArgumentParser:
    """Create the main argument parser."""
    parser = argparse.ArgumentParser(
        prog='asa-ctrl',
        description='ARK: Survival Ascended Server Control Tool'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    for command in COMMANDS:
        command.add_parser(subparsers)
    
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
    parsed_args.settings = AsaSettings()
    # Lazy debug output if user enabled verbose logging
    settings = parsed_args.settings
    if settings.start_params() and logger.isEnabledFor(10):  # DEBUG level
        logger.debug("Parsed start params: %s", settings.parse_start_params())
    
    # Execute the appropriate command
    if hasattr(parsed_args, 'func'):
        parsed_args.func(parsed_args)
    else:
        parser.print_help()
        sys.exit(ExitCodes.OK)


if __name__ == '__main__':
    main()
