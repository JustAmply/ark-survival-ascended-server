#!/usr/bin/env python3
"""Simple in-process scheduler for graceful ASA server restarts."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Sequence, Tuple

LOG_PREFIX = "[asa-restart-scheduler]"
RESTART_COMMAND = os.environ.get("ASA_RESTART_COMMAND", "/usr/bin/restart_server.sh")
CRON_EXPRESSION = os.environ.get("SERVER_RESTART_CRON", "").strip()
WARNING_OFFSETS = os.environ.get("SERVER_RESTART_WARNINGS", "30,5,1")
SLEEP_GRANULARITY = 30  # seconds

_stop_requested = False


def log(message: str) -> None:
    print(f"{LOG_PREFIX} {message}", flush=True)


def handle_stop(signum: int, frame) -> None:  # type: ignore[override]
    global _stop_requested
    _stop_requested = True
    log(f"Received signal {signum} - stopping scheduler")


for _sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
    signal.signal(_sig, handle_stop)


class ScheduleError(RuntimeError):
    """Raised when the cron expression cannot be parsed."""


@dataclass
class CronField:
    values: Sequence[int]
    any_value: bool

    def contains(self, value: int) -> bool:
        return value in self.values


@dataclass
class CronSchedule:
    minute: CronField
    hour: CronField
    day: CronField
    month: CronField
    weekday: CronField

    @classmethod
    def parse(cls, expression: str) -> "CronSchedule":
        parts = expression.split()
        if len(parts) != 5:
            raise ScheduleError("Cron expression must contain exactly five fields")

        fields = (
            _parse_field(parts[0], 0, 59),
            _parse_field(parts[1], 0, 23),
            _parse_field(parts[2], 1, 31),
            _parse_field(parts[3], 1, 12),
            _parse_field(parts[4], 0, 7, allow_seven=True),
        )

        return cls(*fields)

    def matches(self, moment: datetime) -> bool:
        minute = moment.minute
        hour = moment.hour
        day = moment.day
        month = moment.month
        weekday = (moment.weekday() + 1) % 7  # convert Monday=0 -> Cron Sunday=0

        if month not in self.month.values:
            return False

        minute_ok = self.minute.contains(minute)
        hour_ok = self.hour.contains(hour)
        day_ok = self.day.contains(day)
        weekday_ok = self.weekday.contains(weekday)

        # Cron semantics: if either DOM or DOW is restricted, both must match accordingly
        if not self.day.any_value and not self.weekday.any_value:
            if not (day_ok or weekday_ok):
                return False
        else:
            if not self.day.any_value and not day_ok:
                return False
            if not self.weekday.any_value and not weekday_ok:
                return False

        return minute_ok and hour_ok

    def next_after(self, moment: datetime) -> datetime:
        cursor = moment.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(60 * 24 * 366 * 5):  # up to 5 years worth of minutes
            if self.matches(cursor):
                return cursor
            cursor += timedelta(minutes=1)
        raise ScheduleError("Unable to find next execution time within 5 years")


def _parse_field(field: str, minimum: int, maximum: int, *, allow_seven: bool = False) -> CronField:
    raw = field.strip()
    any_value = raw in {"*", "*/1"}
    values: List[int] = []

    for part in raw.split(",") if raw else []:
        part = part.strip()
        if not part:
            continue

        if part == "*":
            values.extend(range(minimum, maximum + 1))
            continue

        if "/" in part:
            range_part, step_part = part.split("/", 1)
            step = _parse_int(step_part, "step")
            if step <= 0:
                raise ScheduleError("Step value must be positive")
        else:
            range_part, step = part, 1

        if range_part == "*":
            start, end = minimum, maximum
        elif "-" in range_part:
            start_part, end_part = range_part.split("-", 1)
            start = _parse_int(start_part, "range start")
            end = _parse_int(end_part, "range end")
        else:
            start = end = _parse_int(range_part, "value")

        if start < minimum or end > maximum or start > end:
            raise ScheduleError("Value out of bounds for field")

        value = start
        while value <= end:
            if value not in values:
                values.append(0 if allow_seven and value == 7 else value)
            value += step

    if not values:
        values = list(range(minimum, maximum + 1))

    if allow_seven:
        values = [0 if v == 7 else v for v in values]

    values = sorted(dict.fromkeys(values))
    return CronField(values=tuple(values), any_value=any_value or raw == "")


def _parse_int(value: str, context: str) -> int:
    try:
        return int(value)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ScheduleError(f"Invalid {context}: {value!r}") from exc


def _parse_warnings(raw: str) -> List[int]:
    offsets: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError:
            log(f"Ignoring invalid warning offset: {part!r}")
            continue
        if value > 0:
            offsets.append(value)
    # Remove duplicates while keeping descending order for scheduling convenience
    seen = set()
    unique_desc = []
    for value in sorted(offsets, reverse=True):
        if value not in seen:
            unique_desc.append(value)
            seen.add(value)
    return unique_desc


def _sleep_until(target: datetime) -> bool:
    while not _stop_requested:
        now = datetime.now()
        remaining = (target - now).total_seconds()
        if remaining <= 0:
            return True
        time.sleep(min(SLEEP_GRANULARITY, remaining))
    return False


def _run_command(args: Sequence[str]) -> None:
    try:
        subprocess.run(args, check=True)
    except FileNotFoundError:
        log(f"Command not found: {args[0]}")
    except subprocess.CalledProcessError as exc:
        log(f"Command {args} exited with {exc.returncode}")


def _broadcast_warning(offset: int) -> None:
    minutes = "minute" if offset == 1 else "minutes"
    message = f"Server restart in {offset} {minutes}."
    log(f"Broadcasting restart warning ({offset} {minutes})")
    _run_command([RESTART_COMMAND, "warn", message])


def _trigger_restart() -> None:
    log("Triggering scheduled restart")
    _run_command([RESTART_COMMAND])


def scheduler_loop(schedule: CronSchedule, warnings: Sequence[int]) -> None:
    while not _stop_requested:
        now = datetime.now()
        next_fire = schedule.next_after(now)
        log(f"Next restart at {next_fire.isoformat(timespec='minutes')}")

        events: List[Tuple[datetime, Tuple[str, int | None]]] = []
        for offset in warnings:
            warn_time = next_fire - timedelta(minutes=offset)
            if warn_time > now:
                events.append((warn_time, ("warn", offset)))

        events.append((next_fire, ("restart", None)))
        events.sort(key=lambda item: item[0])

        for when, action in events:
            if not _sleep_until(when):
                return
            if _stop_requested:
                return
            kind, value = action
            if kind == "warn" and value is not None:
                _broadcast_warning(value)
            elif kind == "restart":
                _trigger_restart()


def main() -> int:
    if not CRON_EXPRESSION:
        return 0

    log(f"Using cron expression: {CRON_EXPRESSION}")
    try:
        schedule = CronSchedule.parse(CRON_EXPRESSION)
    except ScheduleError as exc:
        log(f"Invalid cron expression: {exc}")
        return 1

    warnings = _parse_warnings(WARNING_OFFSETS)
    if warnings:
        log(f"Configured restart warnings (minutes before): {warnings}")
    else:
        log("Restart warnings disabled")

    scheduler_loop(schedule, warnings)
    log("Scheduler stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
