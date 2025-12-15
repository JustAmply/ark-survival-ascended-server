from __future__ import annotations

from datetime import datetime, timedelta

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import asa_ctrl.core.restart_scheduler as scheduler  # noqa: E402
from asa_ctrl.core.restart_scheduler import CronSchedule, parse_warning_offsets, run_scheduler  # noqa: E402


def make_dt(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M")


def test_cron_schedule_basic_minute_progression():
    schedule = CronSchedule("0 4 * * *")
    assert schedule.next_run(make_dt("2024-03-10 03:59")) == make_dt("2024-03-10 04:00")
    # After the run it should point to the next day
    assert schedule.next_run(make_dt("2024-03-10 04:00")) == make_dt("2024-03-11 04:00")


def test_cron_schedule_weekday_or_dom_matching():
    # First day of month or every Monday at noon
    schedule = CronSchedule("0 12 1 * 1")
    # Monday should match via weekday selection
    assert schedule.next_run(make_dt("2024-09-30 11:00")) == make_dt("2024-09-30 12:00")
    # Subsequent run targets the 1st of the month
    assert schedule.next_run(make_dt("2024-09-30 12:00")) == make_dt("2024-10-01 12:00")
    # If already past first but before Monday, next Monday should be selected
    assert schedule.next_run(make_dt("2024-10-01 12:01")) == make_dt("2024-10-07 12:00")


def test_cron_schedule_range_and_step():
    schedule = CronSchedule("*/15 8-9 * * mon-fri")
    assert schedule.next_run(make_dt("2024-06-03 08:00")) == make_dt("2024-06-03 08:15")
    assert schedule.next_run(make_dt("2024-06-03 08:59")) == make_dt("2024-06-03 09:00")


def test_cron_schedule_accepts_seven_in_weekday_ranges():
    schedule = CronSchedule("0 0 * * 1-7")
    assert schedule.next_run(make_dt("2024-03-09 23:59")) == make_dt("2024-03-10 00:00")


def test_cron_schedule_accepts_seven_as_sunday():
    schedule = CronSchedule("0 0 * * 7")
    assert schedule.next_run(make_dt("2024-03-09 23:59")) == make_dt("2024-03-10 00:00")


def test_parse_warning_offsets_default_and_custom():
    assert parse_warning_offsets("") == [30, 5, 1]
    assert parse_warning_offsets("15, 5 ,1") == [15, 5, 1]
    with pytest.raises(ValueError):
        parse_warning_offsets("0,5")
    with pytest.raises(ValueError):
        parse_warning_offsets("abc")


def test_run_scheduler_no_cron_exits_quickly(monkeypatch):
    # Ensure the scheduler returns immediately when no cron is configured
    monkeypatch.setenv("SERVER_RESTART_CRON", "")
    # Speed up logging to avoid output clutter
    run_scheduler()


def test_run_scheduler_invalid_cron(monkeypatch, caplog):
    monkeypatch.setenv("SERVER_RESTART_CRON", "invalid")
    with caplog.at_level("INFO"):
        run_scheduler()
    assert "Invalid SERVER_RESTART_CRON" in "\n".join(caplog.messages)


def test_run_scheduler_announces_and_triggers(monkeypatch):
    base_time = datetime(2024, 1, 1, 12, 0)

    class FakeDateTime(datetime):
        current = base_time

        @classmethod
        def now(cls):
            return cls.current

        @classmethod
        def advance(cls, seconds: float) -> None:
            cls.current = cls.current + timedelta(seconds=seconds)

    def fast_sleep(seconds: float) -> None:
        FakeDateTime.advance(seconds)

    calls = []

    def fake_run_rcon(command: str, _logger) -> bool:
        calls.append(command)
        return True

    stop_marker = object()

    def fake_trigger(_path, _logger):
        raise RuntimeError(stop_marker)

    monkeypatch.setenv("SERVER_RESTART_CRON", "* * * * *")
    monkeypatch.setenv("SERVER_RESTART_WARNINGS", "1")
    monkeypatch.setenv("ASA_SUPERVISOR_PID_FILE", "/tmp/unused.pid")

    monkeypatch.setattr(scheduler, "datetime", FakeDateTime)
    monkeypatch.setattr(scheduler.time, "sleep", fast_sleep)
    monkeypatch.setattr(scheduler, "_run_rcon_command", fake_run_rcon)
    monkeypatch.setattr(scheduler, "_trigger_restart", fake_trigger)

    with pytest.raises(RuntimeError) as exc:
        run_scheduler()

    assert exc.value.args and exc.value.args[0] is stop_marker
    # Expect warning and final announcement
    assert any("restart in 1 minute" in message for message in calls)
    assert any("restarting now" in message for message in calls)
