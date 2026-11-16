"""Known configuration checks must be useful without changing user data."""

import argparse
import json

import pytest

from asa_ctrl.common.config import AsaSettings
from asa_ctrl.common.constants import ExitCodes
from asa_ctrl.common.errors import AsaCtrlError
from asa_ctrl.cli_commands.config_command import ConfigCommand
from asa_ctrl.core import diagnostics


def settings(tmp_path, **overrides):
    values = {
        "ASA_MAP": "TheIsland_WP",
        "ASA_SERVER_ADMIN_PASSWORD": "private-value",
        "ASA_GAME_USER_SETTINGS_PATH": str(tmp_path / "GameUserSettings.ini"),
        "ASA_GAME_INI_PATH": str(tmp_path / "Game.ini"),
        "ASA_MOD_DATABASE_PATH": str(tmp_path / "mods.json"),
    }
    values.update(overrides)
    return AsaSettings(values)


@pytest.mark.parametrize("overrides, field", [
    ({"ASA_PORT": "70000"}, "Port"),
    ({"ASA_RCON_PORT": "oops"}, "RCONPort"),
    ({"ASA_MAX_PLAYERS": "0"}, "WinLiveMaxPlayers"),
    ({"ASA_RCON_ENABLED": "maybe"}, "ASA_RCON_ENABLED"),
    ({"ASA_SHUTDOWN_TIMEOUT": "-1"}, "ASA_SHUTDOWN_TIMEOUT"),
    ({"ASA_RESTART_MAX_FAILURES": "invalid"}, "ASA_RESTART_MAX_FAILURES"),
    ({"ASA_VALIDATE": "sometimes"}, "ASA_VALIDATE"),
    ({"ASA_UPDATE": "never"}, "ASA_UPDATE"),
    ({"SERVER_RESTART_CRON": "90 4 * * *"}, "SERVER_RESTART_CRON"),
    ({"SERVER_RESTART_WARNINGS": "30,-1"}, "SERVER_RESTART_WARNINGS"),
    ({"PROTON_SKIP_CHECKSUM": "yes"}, "PROTON_SKIP_CHECKSUM"),
])
def test_invalid_known_settings_are_rejected(tmp_path, overrides, field):
    result = diagnostics.check_configuration(settings(tmp_path, **overrides))
    assert not result["ok"]
    assert any(field in error for error in result["errors"])


def test_effective_overlay_and_unknown_flags_are_accepted(tmp_path):
    result = diagnostics.check_configuration(settings(
        tmp_path, ASA_START_PARAMS="Map?Port=bad -CustomOption=anything",
        ASA_PORT="7777", ASA_UPDATE="manual", SERVER_RESTART_CRON="0 4 * * mon-fri",
    ))
    assert result["ok"]


def test_udp_game_and_tcp_rcon_can_use_same_number(tmp_path):
    result = diagnostics.check_configuration(settings(tmp_path, ASA_PORT="7777", ASA_RCON_PORT="7777"))
    assert result["ok"]


def test_two_udp_ports_cannot_conflict(tmp_path):
    result = diagnostics.check_configuration(settings(tmp_path, ASA_EXTRA_QUERY_PARAMS="QueryPort=7777"))
    assert not result["ok"]
    assert any("same UDP port" in error for error in result["errors"])


def test_disabled_rcon_warns_about_shutdown(tmp_path):
    result = diagnostics.check_configuration(settings(tmp_path, ASA_RCON_ENABLED="false"))
    assert result["ok"]
    assert any("saveworld" in warning for warning in result["warnings"])


def test_strict_password_mode_warns_but_accepts_explicit_default(tmp_path):
    result = diagnostics.check_configuration(settings(
        tmp_path, ASA_SERVER_ADMIN_PASSWORD="changeme", ASA_REQUIRE_ADMIN_PASSWORD="1",
    ))
    assert result["ok"]
    assert any("non-default" in warning for warning in result["warnings"])


@pytest.mark.parametrize("strict, ini_password, valid, warns", [
    ("1", "", False, True),
    ("1", "ini-private-value", True, False),
    ("1", "changeme", True, True),
    ("0", "", True, True),
    ("0", "ini-private-value", True, True),
])
def test_empty_launch_configuration_matches_runtime_password_fallback(
    tmp_path, strict, ini_password, valid, warns,
):
    ini = tmp_path / "GameUserSettings.ini"
    ini.write_text(f"[ServerSettings]\nServerAdminPassword={ini_password}\n", encoding="utf-8")
    configuration = AsaSettings({
        "ASA_GAME_USER_SETTINGS_PATH": str(ini), "ASA_REQUIRE_ADMIN_PASSWORD": strict,
    })
    result = diagnostics.check_configuration(configuration)
    assert result["ok"] is valid
    assert bool(result["warnings"]) is warns
    output = diagnostics.show_configuration(configuration)
    assert output["launch"]["ServerAdminPassword"] == ("<redacted>" if valid else None)


def test_configuration_resolution_error_does_not_echo_secrets(tmp_path, monkeypatch):
    configuration = settings(tmp_path)

    def fail():
        raise AsaCtrlError("private-secret-content")

    monkeypatch.setattr(configuration, "launch_configuration", fail)
    result = diagnostics.check_configuration(configuration)
    assert not result["ok"]
    assert "private-secret-content" not in json.dumps(result)


def test_show_redacts_all_passwords_and_omits_unknown_values(tmp_path):
    result = diagnostics.show_configuration(settings(
        tmp_path, ASA_SERVER_PASSWORD="join-secret", ASA_SPECTATOR_PASSWORD="spectator-secret",
        ASA_EXTRA_FLAGS="-ApiToken=token-secret",
    ))
    output = json.dumps(result)
    assert "private-value" not in output
    assert "join-secret" not in output
    assert "spectator-secret" not in output
    assert "token-secret" not in output
    assert output.count("<redacted>") == 3


def test_doctor_checks_permissions_without_creating_files(tmp_path, monkeypatch):
    for key in ("SERVER_FILES_DIR", "STEAMCMD_DIR", "STEAM_HOME_DIR"):
        monkeypatch.setattr(diagnostics, key, str(tmp_path))
    result = diagnostics.check_configuration(settings(tmp_path), filesystem=True)
    assert result["ok"]
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setattr(diagnostics.os, "access", lambda *_args: False)
    result = diagnostics.check_configuration(settings(tmp_path), filesystem=True)
    assert not result["ok"]
    assert any("writable" in error for error in result["errors"])
    assert list(tmp_path.iterdir()) == []


def test_cli_reports_machine_readable_errors(tmp_path, capsys):
    parser = argparse.ArgumentParser()
    ConfigCommand.add_parser(parser.add_subparsers())
    args = parser.parse_args(["config", "check", "--json"])
    args.settings = settings(tmp_path, ASA_PORT="bad-private-value")
    with pytest.raises(SystemExit) as exc:
        args.func(args)
    assert exc.value.code == ExitCodes.CONFIGURATION_ERROR
    output = capsys.readouterr().out
    assert not json.loads(output)["ok"]
    assert "bad-private-value" not in output
