"""Mod management command handling for the asa-ctrl CLI."""

import argparse
import sys

from asa_ctrl.cli_helpers import exit_with_error, map_exception_to_exit_code
from asa_ctrl.common.constants import ExitCodes
from asa_ctrl.common.errors import CorruptedModsDatabaseError, ModAlreadyEnabledError
from asa_ctrl.common.config import AsaSettings
from asa_ctrl.core.mods import ModDatabase, format_mod_list_for_server


class ModsCommand:
    """Handles mod management commands."""

    @staticmethod
    def add_parser(subparsers) -> None:
        """Add mods command parser to subparsers."""
        parser = subparsers.add_parser('mods', help='Interface for mod management')

        mod_subparsers = parser.add_subparsers(dest='mod_action', help='Mod actions')

        enable_parser = mod_subparsers.add_parser('enable', help='Enable a mod')
        enable_parser.add_argument('mod_id', type=int, help='The mod ID to enable')

        disable_parser = mod_subparsers.add_parser('disable', help='Disable a mod')
        disable_parser.add_argument('mod_id', type=int, help='The mod ID to disable')

        remove_parser = mod_subparsers.add_parser('remove', help='Remove a mod entry entirely')
        remove_parser.add_argument('mod_id', type=int, help='The mod ID to remove from the database')

        list_parser = mod_subparsers.add_parser('list', help='List all mods')
        list_parser.add_argument('--enabled-only', action='store_true', help='Show only enabled mods')

        parser.set_defaults(func=ModsCommand.execute)

        hidden = subparsers.add_parser('mods-string', help=argparse.SUPPRESS)
        hidden.set_defaults(func=ModsCommand.print_mods_string)

    @staticmethod
    def execute(args) -> None:
        """Execute a mod management command."""
        try:
            if args.mod_action == 'enable':
                ModsCommand._enable_mod(args)
            elif args.mod_action == 'disable':
                ModsCommand._disable_mod(args)
            elif args.mod_action == 'remove':
                ModsCommand._remove_mod(args)
            elif args.mod_action == 'list':
                ModsCommand._list_mods(args)
            else:
                print("Please specify a mod action: enable, disable, remove, or list")
                sys.exit(ExitCodes.OK)

        except Exception as exc:
            exit_code = map_exception_to_exit_code(exc)
            if isinstance(exc, CorruptedModsDatabaseError):
                message = str(exc)
            elif isinstance(exc, ModAlreadyEnabledError):
                message = (
                    "This mod is already enabled! Use 'asa-ctrl mods list' to see what mods are currently enabled."
                )
            else:
                message = f"Mod command failed: {exc}"

            if exit_code is None:
                exit_code = ExitCodes.CORRUPTED_MODS_DATABASE

            exit_with_error(message, exit_code)

    @staticmethod
    def _enable_mod(args) -> None:
        """Enable a mod."""
        db = ModsCommand._get_db(args)
        db.enable_mod(args.mod_id)
        print(f"Enabled mod id '{args.mod_id}' successfully. The server will download the mod upon startup.")

    @staticmethod
    def _disable_mod(args) -> None:
        """Disable a mod."""
        db = ModsCommand._get_db(args)
        if db.disable_mod(args.mod_id):
            print(f"Disabled mod id '{args.mod_id}' successfully.")
        else:
            print(f"Mod id '{args.mod_id}' was not found in the database.")

    @staticmethod
    def _remove_mod(args) -> None:
        """Remove a mod entry entirely."""
        db = ModsCommand._get_db(args)
        if db.remove_mod(args.mod_id):
            print(f"Removed mod id '{args.mod_id}' successfully.")
        else:
            print(f"Mod id '{args.mod_id}' was not found in the database.")

    @staticmethod
    def _list_mods(args) -> None:
        """List mods."""
        db = ModsCommand._get_db(args)

        if args.enabled_only:
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

    @staticmethod
    def print_mods_string(args) -> None:
        """Print the formatted mods parameter string only."""
        settings = getattr(args, "settings", None)
        if not isinstance(settings, AsaSettings):
            settings = AsaSettings()
        print(format_mod_list_for_server(settings), end="")

    @staticmethod
    def _get_db(args) -> ModDatabase:
        settings = getattr(args, "settings", None)
        if not isinstance(settings, AsaSettings):
            settings = AsaSettings()
        return ModDatabase.from_settings(settings)
