"""Utilities for scheduling automated server restarts."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Sequence, Tuple

from .logging_config import configure_logging, get_logger


@dataclass(frozen=True)
class CronField:
    """Represents a parsed cron field."""

    values: Sequence[int]
    is_wildcard: bool


class CronSchedule:
    """Simple cron schedule evaluator supporting 5-field expressions."""

    def __init__(self, expression: str) -> None:
        self.expression = expression
        parts = [part.strip() for part in expression.split() if part.strip()]
        if len(parts) != 5:
            raise ValueError("Cron expression must have exactly 5 fields (minute hour day month weekday)")

        self.minutes = self._parse_field(parts[0], 0, 59)
        self.hours = self._parse_field(parts[1], 0, 23)
        self.days = self._parse_field(parts[2], 1, 31, allow_question=True)
        self.months = self._parse_field(parts[3], 1, 12, allow_names=True)
        self.weekdays = self._parse_field(parts[4], 0, 6, allow_names=True, allow_question=True, allow_seven=True)

    @staticmethod
    def _parse_field(
        field: str,
        minimum: int,
        maximum: int,
        *,
        allow_names: bool = False,
        allow_question: bool = False,
        allow_seven: bool = False,
    ) -> CronField:
        if not field:
            raise ValueError("Empty cron field")

        original_field = field
        if allow_question and field == "?":
            field = "*"

        is_wildcard = field == "*"
        names = {}
        if allow_names:
            names = {
                "jan": 1,
                "feb": 2,
                "mar": 3,
                "apr": 4,
                "may": 5,
                "jun": 6,
                "jul": 7,
                "aug": 8,
                "sep": 9,
                "oct": 10,
                "nov": 11,
                "dec": 12,
                "sun": 0,
                "mon": 1,
                "tue": 2,
                "wed": 3,
                "thu": 4,
                "fri": 5,
                "sat": 6,
            }

        def resolve(value: str) -> int:
            value_lower = value.lower()
            if allow_names and value_lower in names:
                return names[value_lower]
            try:
                resolved = int(value)
            except ValueError as exc:  # pragma: no cover - defensive
                raise ValueError(f"Invalid cron value '{value}'") from exc
            return resolved

        def in_bounds(value: int) -> bool:
            if minimum <= value <= maximum:
                return True
            if allow_seven and value == 7:
                return True
            return False

        values: List[int] = []
        for part in field.split(","):
            part = part.strip()
            if not part:
                raise ValueError(f"Empty cron field segment in '{original_field}'")

            step = 1
            if "/" in part:
                range_part, step_part = part.split("/", 1)
                if not step_part:
                    raise ValueError(f"Missing step in cron segment '{part}'")
                try:
                    step = int(step_part)
                except ValueError as exc:
                    raise ValueError(f"Invalid step '{step_part}' in cron segment '{part}'") from exc
                if step <= 0:
                    raise ValueError(f"Step must be positive in cron segment '{part}'")
            else:
                range_part = part

            if range_part in {"*", ""}:
                start = minimum
                end = maximum
            elif "-" in range_part:
                start_str, end_str = range_part.split("-", 1)
                start = resolve(start_str)
                end = resolve(end_str)
            else:
                start = resolve(range_part)
                end = start

            if not in_bounds(start) or not in_bounds(end):
                raise ValueError(f"Cron value out of bounds in segment '{part}'")
            if end < start:
                raise ValueError(f"Invalid range '{part}' in cron field")

            for candidate in range(start, end + 1, step):
                if not in_bounds(candidate):
                    continue
                normalized = 0 if allow_seven and candidate == 7 else candidate
                if normalized not in values:
                    values.append(normalized)

        values.sort()
        return CronField(tuple(values), is_wildcard)

    def next_run(self, reference: datetime) -> datetime:
        """Return the next scheduled time strictly after ``reference``."""

        # Work on minute precision
        current = reference.replace(second=0, microsecond=0) + timedelta(minutes=1)

        attempts = 0
        limit = 366 * 24 * 60  # One year of minutes safety limit
        while attempts <= limit:
            if self._matches(current):
                return current
            current += timedelta(minutes=1)
            attempts += 1
        raise ValueError("Unable to resolve next cron run within one year")

    def _matches(self, candidate: datetime) -> bool:
        if candidate.minute not in self.minutes.values:
            return False
        if candidate.hour not in self.hours.values:
            return False
        if candidate.month not in self.months.values:
            return False

        day_match = candidate.day in self.days.values
        cron_weekday = (candidate.weekday() + 1) % 7
        weekday_match = cron_weekday in self.weekdays.values

        if not self.days.is_wildcard and not self.weekdays.is_wildcard:
            if not (day_match or weekday_match):
                return False
        else:
            if not self.days.is_wildcard and not day_match:
                return False
            if not self.weekdays.is_wildcard and not weekday_match:
                return False
        return True


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
    exe = os.environ.get("ASA_CTRL_BIN", "/usr/local/bin/asa-ctrl")
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
        os.kill(pid, signal.SIGUSR1)
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
                time.sleep(min(delta, 30))

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
        time.sleep(5)


__all__ = ["CronSchedule", "parse_warning_offsets", "run_scheduler"]
