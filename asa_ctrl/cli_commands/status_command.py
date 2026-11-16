"""Status command and Docker healthcheck exit-code adapter."""

import json
import sys

from asa_ctrl.common.constants import ExitCodes
from asa_ctrl.core.status import server_status


class StatusCommand:
    @staticmethod
    def add_parser(subparsers) -> None:
        parser = subparsers.add_parser("status", help="Check runtime state and RCON readiness")
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--healthcheck", action="store_true", help="Use Docker's 0/1 exit codes")
        parser.set_defaults(func=StatusCommand.execute)

    @staticmethod
    def execute(args) -> None:
        result = server_status(args.settings)
        print(json.dumps(result) if args.json else result["state"])
        if not result["ready"]:
            sys.exit(1 if args.healthcheck else ExitCodes.SERVER_NOT_READY)
