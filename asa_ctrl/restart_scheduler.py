"""Utilities for scheduling automated server restarts."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from croniter import croniter
from croniter.croniter import CroniterBadCronError

from .logging_config import configure_logging, get_logger


DEFAULT_ASA_CTRL_BIN = "/usr/local/bin/asa-ctrl"
MAX_SLEEP_INTERVAL_SECONDS = 30
POST_RESTART_DELAY_SECONDS = 10


class CronSchedule:
    """Cron schedule helper backed by :mod:`croniter`."""

    def __init__(self, expression: str) -> None:
        self._expression = expression
        self._validate_expression()

    def _validate_expression(self) -> None:
        """Eagerly validate cron syntax so we fail fast on start-up."""

        try:
            croniter(self._expression, datetime.now())
        except CroniterBadCronError as exc:
            raise ValueError(str(exc)) from exc

    def next_run(self, reference: datetime) -> datetime:
        """Return the next scheduled time strictly after ``reference``."""

        try:
            iterator = croniter(
                self._expression,
                reference,
                ret_type=datetime,
            )
            return iterator.get_next(datetime)
        except CroniterBadCronError as exc:  # pragma: no cover - defensive
            raise ValueError(str(exc)) from exc


def parse_warning_offsets(raw: str) -> List[int]:
    """Parse a comma separated string of minute offsets."""

    if not raw:
        return [30, 5, 1]

    values: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError as exc:
            raise ValueError(f"Invalid restart warning offset '{part}'") from exc
        if value <= 0:
            raise ValueError("Restart warnings must be positive minute values")
        if value not in values:
            values.append(value)
    if not values:
        raise ValueError("No valid restart warning offsets provided")
    values.sort(reverse=True)
    return values


def _read_pid_from_file(path: Optional[str]) -> Optional[int]:
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read().strip()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    if not content:
        return None
    try:
        return int(content)
    except ValueError:
        return None


def _is_process_alive(pid: Optional[int]) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _run_rcon_command(command: str, logger) -> bool:
    exe = os.environ.get("ASA_CTRL_BIN", DEFAULT_ASA_CTRL_BIN)
    result = subprocess.run(
        [exe, "rcon", "--exec", command],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        logger.warning("Failed to execute RCON command '%s': %s", command, result.stderr.strip())
        return False
    return True


def _announce(minutes: int, target: datetime, logger) -> None:
    time_str = target.strftime("%H:%M")
    if minutes == 1:
        message = f"Server restart in 1 minute (scheduled {time_str})."
    else:
        message = f"Server restart in {minutes} minutes (scheduled {time_str})."
    _run_rcon_command(f"serverchat {message}", logger)


def _announce_now(target: datetime, logger) -> None:
    time_str = target.strftime("%H:%M")
    _run_rcon_command(f"serverchat Server restarting now (scheduled {time_str}).", logger)


def _trigger_restart(supervisor_pid_file: Optional[str], logger) -> None:
    pid = _read_pid_from_file(supervisor_pid_file)
    if pid is None:
        logger.error("Cannot trigger restart - supervisor PID file missing (%s)", supervisor_pid_file)
        return
    if not _is_process_alive(pid):
        logger.error("Cannot trigger restart - supervisor PID %s not alive", pid)
        return
    logger.info("Triggering scheduled restart via signal to PID %s", pid)
    try:
        os.kill(pid, signal.SIGUSR1) # type: ignore // SIGUSR1 may not be defined on Windows
    except ProcessLookupError:
        logger.error("Failed to trigger restart - supervisor process %s not found", pid)


def run_scheduler() -> None:
    """Entry point that waits for cron events and orchestrates restarts."""

    configure_logging()
    logger = get_logger(__name__)

    cron_expression = os.environ.get("SERVER_RESTART_CRON", "").strip()
    if not cron_expression:
        logger.info("Restart scheduler disabled (no cron expression provided)")
        return

    warnings_raw = os.environ.get("SERVER_RESTART_WARNINGS", "")
    try:
        warnings = parse_warning_offsets(warnings_raw)
    except ValueError as exc:
        logger.error("Invalid restart warning configuration: %s", exc)
        return

    try:
        schedule = CronSchedule(cron_expression)
    except ValueError as exc:
        logger.error("Invalid SERVER_RESTART_CRON expression '%s': %s", cron_expression, exc)
        return

    supervisor_pid_file = os.environ.get("ASA_SUPERVISOR_PID_FILE")
    server_pid_file = os.environ.get("ASA_SERVER_PID_FILE")

    logger.info(
        "Restart scheduler active (cron='%s', warnings=%s)",
        cron_expression,
        warnings,
    )

    while True:
        now = datetime.now()
        try:
            next_run = schedule.next_run(now)
        except ValueError as exc:
            logger.error("Failed to compute next restart time: %s", exc)
            return

        logger.info("Next scheduled restart at %s", next_run.strftime("%Y-%m-%d %H:%M"))

        events: List[Tuple[str, datetime, Optional[int]]] = []
        for offset in warnings:
            warning_time = next_run - timedelta(minutes=offset)
            if warning_time >= now:
                events.append(("warn", warning_time, offset))
        events.sort(key=lambda item: item[1])
        events.append(("restart", next_run, None))

        for event_type, event_time, payload in events:
            while True:
                now = datetime.now()
                delta = (event_time - now).total_seconds()
                if delta <= 0:
                    break
                time.sleep(min(delta, MAX_SLEEP_INTERVAL_SECONDS))

            if server_pid_file and not _is_process_alive(_read_pid_from_file(server_pid_file)):
                logger.info("Server process not running - postponing notifications until it comes back")
                break

            if event_type == "warn" and payload is not None:
                logger.info("Announcing restart %s minutes before scheduled time", payload)
                _announce(payload, next_run, logger)
            elif event_type == "restart":
                logger.info("Scheduled restart window reached - notifying players and signalling supervisor")
                _announce_now(next_run, logger)
                _trigger_restart(supervisor_pid_file, logger)
                break

        # Small delay before computing next window to avoid tight loops when server is down
        time.sleep(POST_RESTART_DELAY_SECONDS)


__all__ = ["CronSchedule", "parse_warning_offsets", "run_scheduler"]
