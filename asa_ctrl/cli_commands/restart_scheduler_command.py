"""Restart scheduler command handling for the asa-ctrl CLI."""

from asa_ctrl.core.restart_scheduler import run_scheduler


class RestartSchedulerCommand:
    """Internal command to run the restart scheduler loop."""

    @staticmethod
    def add_parser(subparsers) -> None:
        parser = subparsers.add_parser(
            'restart-scheduler',
            help='Run the internal restart scheduler (used by entrypoint)',
        )
        parser.set_defaults(func=RestartSchedulerCommand.execute)

    @staticmethod
    def execute(_args) -> None:
        run_scheduler()
