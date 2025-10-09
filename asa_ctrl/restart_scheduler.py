"""Utilities for scheduling automated server restarts."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from .logging_config import configure_logging, get_logger


DEFAULT_ASA_CTRL_BIN = "/usr/local/bin/asa-ctrl"
MAX_SLEEP_INTERVAL_SECONDS = 30
POST_RESTART_DELAY_SECONDS = 10


_MONTH_NAMES: Dict[str, int] = {
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
}

_WEEKDAY_NAMES: Dict[str, int] = {
    "sun": 0,
    "mon": 1,
    "tue": 2,
    "wed": 3,
    "thu": 4,
    "fri": 5,
    "sat": 6,
}


class CronSchedule:
    """Lightweight cron evaluator supporting the subset we rely on."""

    _FIELD_SPECS: Tuple[Tuple[str, int, int, bool, Dict[str, int]], ...] = (
        ("minute", 0, 59, False, {}),
        ("hour", 0, 23, False, {}),
        ("day", 1, 31, True, {}),
        ("month", 1, 12, False, _MONTH_NAMES),
        ("weekday", 0, 6, True, _WEEKDAY_NAMES),
    )

    def __init__(self, expression: str) -> None:
        parts = [part.strip().lower() for part in expression.split() if part.strip()]
        if len(parts) != 5:
            raise ValueError(
                "Cron expression must have exactly 5 fields (minute hour day month weekday)"
            )

        self._fields: List[Optional[Tuple[int, ...]]] = []
        for value, spec in zip(parts, self._FIELD_SPECS):
            self._fields.append(self._parse_field(value, *spec))

    @staticmethod
    def _parse_field(
        raw: str,
        label: str,
        minimum: int,
        maximum: int,
        allow_question: bool,
        names: Dict[str, int],
    ) -> Optional[Tuple[int, ...]]:
        if allow_question and raw == "?":
            raw = "*"
        if raw == "*":
            return None

        def resolve(token: str) -> int:
            token = token.strip().lower()
            if token in names:
                return names[token]
            try:
                return int(token)
            except ValueError as exc:  # pragma: no cover - defensive
                raise ValueError(f"Invalid value '{token}' in cron field '{label}'") from exc

        values: set[int] = set()
        for chunk in raw.split(","):
            chunk = chunk.strip()
            if not chunk:
                raise ValueError(f"Empty value in cron field '{label}'")

            step = 1
            if "/" in chunk:
                base, step_text = chunk.split("/", 1)
                if not step_text:
                    raise ValueError(f"Missing step in cron field '{label}' segment '{chunk}'")
                try:
                    step = int(step_text)
                except ValueError as exc:
                    raise ValueError(
                        f"Invalid step '{step_text}' in cron field '{label}' segment '{chunk}'"
                    ) from exc
                if step <= 0:
                    raise ValueError(f"Step must be positive in cron field '{label}' segment '{chunk}'")
            else:
                base = chunk

            if base in {"*", ""}:
                start, end = minimum, maximum
            elif "-" in base:
                start_text, end_text = base.split("-", 1)
                start, end = resolve(start_text), resolve(end_text)
            else:
                start = end = resolve(base)

            if end < start:
                raise ValueError(f"Invalid range '{chunk}' in cron field '{label}'")

            for candidate in range(start, end + 1, step):
                normalized = 0 if label == "weekday" and candidate == 7 else candidate
                if not (minimum <= normalized <= maximum):
                    raise ValueError(
                        f"Value {candidate} out of bounds for cron field '{label}'"
                    )
                values.add(normalized)

        if not values:
            raise ValueError(f"No values resolved for cron field '{label}'")
        return tuple(sorted(values))

    def next_run(self, reference: datetime) -> datetime:
        """Return the next scheduled time strictly after ``reference``."""

        current = reference.replace(second=0, microsecond=0) + timedelta(minutes=1)
        limit = 366 * 24 * 60  # One year of minutes safety limit
        for _ in range(limit):
            if self._matches(current):
                return current
            current += timedelta(minutes=1)
        raise ValueError("Unable to resolve next cron run within one year")

    def _matches(self, candidate: datetime) -> bool:
        minute_values, hour_values, day_values, month_values, weekday_values = self._fields

        if minute_values is not None and candidate.minute not in minute_values:
            return False
        if hour_values is not None and candidate.hour not in hour_values:
            return False
        if month_values is not None and candidate.month not in month_values:
            return False

        day_match = day_values is None or candidate.day in day_values
        cron_weekday = (candidate.weekday() + 1) % 7
        weekday_match = weekday_values is None or cron_weekday in weekday_values

        if day_values is not None and weekday_values is not None:
            return (candidate.day in day_values) or (cron_weekday in weekday_values)
        return day_match and weekday_match


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
