from __future__ import annotations

from datetime import datetime, timedelta

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import asa_ctrl.core.restart_scheduler as scheduler  # noqa: E402
from asa_ctrl.core.restart_scheduler import (
    CronSchedule,
    parse_warning_offsets,
    run_scheduler,
)


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


def test_parse_warning_offsets_dedup_and_sort():
    assert parse_warning_offsets("5,1,5,10") == [10, 5, 1]


@pytest.mark.parametrize(
    "environment, message",
    [
        ({}, "Restart scheduler disabled"),
        ({"SERVER_RESTART_CRON": "invalid"}, "Invalid SERVER_RESTART_CRON"),
        ({"SERVER_RESTART_CRON": "* * * * *", "SERVER_RESTART_WARNINGS": "0"}, "Invalid restart warning"),
    ],
)
def test_run_scheduler_inactive_configuration_has_no_side_effects(monkeypatch, caplog, environment, message):
    def unexpected_effect(*_args, **_kwargs):
        pytest.fail("Inactive scheduler reached sleep, RCON or process signalling")

    monkeypatch.setattr(scheduler.time, "sleep", unexpected_effect)
    monkeypatch.setattr(scheduler, "execute_rcon_command", unexpected_effect)
    monkeypatch.setattr(scheduler.os, "kill", unexpected_effect)

    with caplog.at_level("INFO"):
        run_scheduler(scheduler.AsaSettings(environment))

    assert message in caplog.text


@pytest.mark.parametrize(
    "supervisor_state, server_alive, rcon_fails",
    [
        ("alive", True, False),
        ("missing", True, False),
        ("invalid", True, False),
        ("dead", True, False),
        ("alive", False, False),
        ("alive", True, True),
    ],
)
def test_run_scheduler_orders_notifications_and_guards_restart(
    tmp_path, monkeypatch, supervisor_state, server_alive, rcon_fails
):
    """Exercise PID guards and announcement ordering through the scheduler owner."""
    class FakeDateTime(datetime):
        current = datetime(2024, 1, 1, 12, 0)

        @classmethod
        def now(cls):
            return cls.current

    class WindowComplete(Exception):
        pass

    sleeps = []

    def fast_sleep(seconds):
        sleeps.append(seconds)
        if FakeDateTime.current >= datetime(2024, 1, 1, 12, 5) or not server_alive:
            raise WindowComplete
        assert len(sleeps) < 30, "Scheduler did not finish its first restart window"
        FakeDateTime.current += timedelta(seconds=seconds)

    supervisor_path = tmp_path / "supervisor.pid"
    if supervisor_state != "missing":
        supervisor_path.write_text("not-an-int" if supervisor_state == "invalid" else "12345", encoding="utf-8")
    server_path = tmp_path / "server.pid"
    server_path.write_text("23456", encoding="utf-8")
    settings = scheduler.AsaSettings({
        "SERVER_RESTART_CRON": "5 12 * * *",
        "SERVER_RESTART_WARNINGS": "5,1",
        "ASA_SUPERVISOR_PID_FILE": str(supervisor_path),
        "ASA_SERVER_PID_FILE": str(server_path),
    })
    events = []

    def fake_execute(command, *, settings):
        assert settings is configured_settings
        events.append(("rcon", command))
        if rcon_fails:
            raise scheduler.AsaCtrlError("RCON unavailable")
        return "ok"

    def fake_kill(pid, signum):
        if signum == 0:
            if (pid == 23456 and not server_alive) or (pid == 12345 and supervisor_state == "dead"):
                raise ProcessLookupError(pid)
            assert pid in (12345, 23456)
        else:
            events.append(("signal", pid, signum))

    configured_settings = settings
    # The image is Linux; provide its signal constant on Windows without sending it.
    monkeypatch.setattr(scheduler.signal, "SIGUSR1", 10, raising=False)
    monkeypatch.setattr(scheduler, "datetime", FakeDateTime)
    monkeypatch.setattr(scheduler.time, "sleep", fast_sleep)
    monkeypatch.setattr(scheduler, "execute_rcon_command", fake_execute)
    monkeypatch.setattr(scheduler.os, "kill", fake_kill)

    with pytest.raises(WindowComplete):
        run_scheduler(settings)

    expected = []
    if server_alive:
        expected = [
            ("rcon", "serverchat Server restart in 5 minutes (scheduled 12:05)."),
            ("rcon", "serverchat Server restart in 1 minute (scheduled 12:05)."),
            ("rcon", "serverchat Server restarting now (scheduled 12:05)."),
        ]
        if supervisor_state == "alive":
            expected.append(("signal", 12345, 10))
    assert events == expected
