"""Update and retry policies do not depend on launching the game."""

import logging

import pytest

from server_runtime.constants import RuntimeSettings
from server_runtime import steamcmd
from server_runtime.supervisor import ServerSupervisor


@pytest.mark.parametrize("mode,completed,installed,expected", [
    ("always", True, True, True),
    ("startup", False, True, True),
    ("startup", True, True, False),
    ("manual", False, True, False),
    ("manual", True, False, True),
    ("startup", True, False, True),
])
def test_update_policy(monkeypatch, mode, completed, installed, expected):
    monkeypatch.setattr(steamcmd, "server_is_installed", lambda: installed)
    assert steamcmd.should_update(RuntimeSettings.from_env({"ASA_UPDATE": mode}), completed) is expected


def test_unknown_update_policy_fails():
    with pytest.raises(ValueError, match="ASA_UPDATE"):
        steamcmd.should_update(RuntimeSettings.from_env({"ASA_UPDATE": "typo"}), False)


def supervisor(**env):
    instance = object.__new__(ServerSupervisor)
    instance.settings = RuntimeSettings.from_env(env)
    instance.logger = logging.getLogger(__name__)
    instance.restart_requested = False
    instance.last_run_duration = 0
    instance.consecutive_failures = 0
    return instance


def test_retry_backoff_stops_at_limit():
    instance = supervisor()
    assert [instance._restart_delay() for _ in range(5)] == [15, 30, 60, 120, None]


def test_unlimited_retry_still_caps_delay():
    instance = supervisor(ASA_RESTART_MAX_FAILURES="0", ASA_RESTART_MAX_DELAY="40")
    assert [instance._restart_delay() for _ in range(5)] == [15, 30, 40, 40, 40]


@pytest.mark.parametrize("scheduled,duration", [(True, 0), (False, 120)])
def test_planned_or_stable_run_resets_failures(scheduled, duration):
    instance = supervisor()
    instance.consecutive_failures = 4
    instance.restart_requested = scheduled
    instance.last_run_duration = duration
    assert instance._restart_delay() == 15
    assert instance.consecutive_failures == 0
