"""Configuration inspection commands with secret-safe output."""

import configparser
import json
import sys

from asa_ctrl.common.constants import ExitCodes
from asa_ctrl.common.errors import AsaCtrlError
from asa_ctrl.core.diagnostics import check_configuration, show_configuration


class ConfigCommand:
    @staticmethod
    def add_parser(subparsers) -> None:
        parser = subparsers.add_parser("config", help="Inspect and validate configuration")
        commands = parser.add_subparsers(dest="config_action", required=True)
        check = commands.add_parser("check", help="Validate known settings without starting the server")
        check.add_argument("--json", action="store_true", help="Print machine-readable results")
        check.set_defaults(func=ConfigCommand.check, filesystem=False)
        show = commands.add_parser("show", help="Show known launch settings with passwords redacted")
        show.set_defaults(func=ConfigCommand.show)
        doctor = subparsers.add_parser("doctor", help="Check configuration and local filesystem access")
        doctor.add_argument("--json", action="store_true", help="Print machine-readable results")
        doctor.set_defaults(func=ConfigCommand.check, filesystem=True)

    @staticmethod
    def check(args) -> None:
        result = check_configuration(args.settings, filesystem=args.filesystem)
        if args.json:
            print(json.dumps(result))
        else:
            print("Configuration check passed." if result["ok"] else "Configuration check failed.")
            for severity in ("errors", "warnings"):
                for message in result[severity]:
                    print(f"{severity[:-1].upper()}: {message}")
        if not result["ok"]:
            sys.exit(ExitCodes.CONFIGURATION_ERROR)

    @staticmethod
    def show(args) -> None:
        try:
            result = show_configuration(args.settings)
        except (AsaCtrlError, OSError, ValueError, configparser.Error):
            print("Cannot resolve launch configuration; check secret files and INI syntax/access.", file=sys.stderr)
            sys.exit(ExitCodes.CONFIGURATION_ERROR)
        print(json.dumps(result, indent=2))
