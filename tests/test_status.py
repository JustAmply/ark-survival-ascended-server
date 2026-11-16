import json
from unittest.mock import MagicMock

import pytest

from asa_ctrl.cli import main
from asa_ctrl.common.config import AsaSettings
from asa_ctrl.common.errors import RconConnectionError
from asa_ctrl.core import status


@pytest.fixture
def configured(tmp_path, monkeypatch):
    pid = tmp_path / "supervisor.pid"
    pid.write_text("42")
    state = pid.with_suffix(".status.json")
    state.write_text(json.dumps({"supervisor_pid": 42, "phase": "running", "failures": 0}))
    monkeypatch.setattr(status, "process_alive", lambda pid: True)
    client = MagicMock()
    monkeypatch.setattr(status, "RconClient", client)
    settings = AsaSettings({"ASA_SUPERVISOR_PID_FILE": str(pid),
                            "ASA_SERVER_ADMIN_PASSWORD": "private-test-password",
                            "ASA_GAME_USER_SETTINGS_PATH": str(tmp_path / "missing.ini")})
    return settings, state, client


def test_readiness_requires_successful_rcon(configured):
    settings, _, client = configured
    result = status.server_status(settings)
    assert result == {"state": "ready", "ready": True, "consecutive_failures": 0}
    client.return_value.__enter__.return_value.execute_command.assert_called_once_with("ListPlayers")
    assert client.call_args.kwargs["retry_count"] == 0
    assert "private-test-password" not in json.dumps(result)


def test_unresponsive_server_is_not_ready(configured):
    settings, _, client = configured
    client.return_value.__enter__.side_effect = RconConnectionError("unreachable")
    assert status.server_status(settings)["state"] == "not-ready"


@pytest.mark.parametrize("phase", ["starting", "retrying", "stopping", "failed"])
def test_non_running_states_do_not_probe(configured, phase):
    settings, state, client = configured
    state.write_text(json.dumps({"supervisor_pid": 42, "phase": phase, "failures": 2}))
    assert status.server_status(settings) == {"state": phase, "ready": False, "consecutive_failures": 2}
    client.assert_not_called()


def test_stale_state_is_not_ready(configured, monkeypatch):
    settings, _, client = configured
    monkeypatch.setattr(status, "process_alive", lambda pid: False)
    assert status.server_status(settings) == {"state": "stopped", "ready": False}
    client.assert_not_called()


@pytest.mark.parametrize("contents", ["{", "[]", '{}', '{"supervisor_pid": 99}'])
def test_invalid_state_is_unknown(configured, contents):
    settings, state, _ = configured
    state.write_text(contents)
    assert status.server_status(settings) == {"state": "unknown", "ready": False}


def test_disabled_rcon_has_explicit_status(configured):
    settings, _, client = configured
    settings._environ["ASA_RCON_ENABLED"] = "false"
    assert status.server_status(settings)["state"] == "rcon-disabled"
    client.assert_not_called()


def test_empty_launch_uses_runtime_defaults_before_ini(configured, tmp_path):
    settings, _, client = configured
    del settings._environ["ASA_SERVER_ADMIN_PASSWORD"]
    ini = tmp_path / "settings.ini"
    ini.write_text("[ServerSettings]\nServerAdminPassword=ini-secret\nRCONPort=12345\n")
    settings._environ["ASA_GAME_USER_SETTINGS_PATH"] = str(ini)
    assert status.server_status(settings)["ready"]
    assert client.call_args.kwargs["password"] == "changeme"
    assert client.call_args.kwargs["port"] == 27020


def test_windows_probe_never_signals_a_process(monkeypatch):
    monkeypatch.setattr(status.os, "name", "nt")
    kill = MagicMock()
    monkeypatch.setattr(status.os, "kill", kill)
    with pytest.raises(OSError, match="Linux"):
        status.process_alive(123)
    kill.assert_not_called()


@pytest.mark.parametrize("arguments,code", [(["status", "--json"], 10), (["status", "--healthcheck"], 1)])
def test_cli_exit_codes(monkeypatch, capsys, arguments, code):
    monkeypatch.setattr("asa_ctrl.cli_commands.status_command.server_status", lambda settings: {"state": "starting", "ready": False})
    with pytest.raises(SystemExit) as exc:
        main(arguments)
    assert exc.value.code == code
    assert "starting" in capsys.readouterr().out
