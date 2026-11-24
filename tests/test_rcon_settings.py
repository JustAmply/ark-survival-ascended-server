import pytest

from asa_ctrl.cli import main
from asa_ctrl.common.config import AsaSettings
from asa_ctrl.common.constants import ExitCodes
from asa_ctrl.common.errors import RconPasswordNotFoundError, RconPortNotFoundError


def test_ini_password_is_literal(tmp_path):
    path = tmp_path / "settings.ini"
    path.write_text("[ServerSettings]\nServerAdminPassword=test%value%%%(abc)s\n")
    settings = AsaSettings({"ASA_GAME_USER_SETTINGS_PATH": str(path)})
    assert settings.get_server_setting("ServerAdminPassword") == "test%value%%%(abc)s"


def test_invalid_password_sources_report_configuration_error(monkeypatch, capsys):
    monkeypatch.setenv("ASA_SERVER_ADMIN_PASSWORD", "synthetic-value")
    monkeypatch.setenv("ASA_SERVER_ADMIN_PASSWORD_FILE", "unused")
    with pytest.raises(SystemExit) as exc:
        main(["rcon", "--exec", "ListPlayers"])
    assert exc.value.code == ExitCodes.CONFIGURATION_ERROR
    error = capsys.readouterr().err
    assert "Invalid server configuration" in error
    assert "synthetic-value" not in error


@pytest.mark.parametrize("env,expected", [
    ({}, (27020, "changeme")),
    ({"ASA_REQUIRE_ADMIN_PASSWORD": "true"}, (27020, "ini%password")),
    ({"ASA_START_PARAMS": "TheIsland_WP?listen"}, (27031, "ini%password")),
    ({"ASA_START_PARAMS": "TheIsland_WP?RCONPort=27032?ServerAdminPassword=legacy"},
     (27032, "legacy")),
    ({"ASA_START_PARAMS": "TheIsland_WP?RCONPort=27032?ServerAdminPassword=legacy",
      "ASA_RCON_PORT": "27033", "ASA_SERVER_ADMIN_PASSWORD": "named"}, (27033, "named")),
    ({"ASA_EXTRA_QUERY_PARAMS": "RCONPort=27034", "ASA_RCON_PORT": "27033"},
     (27034, "ini%password")),
])
def test_managed_rcon_endpoint_matches_launch_precedence(tmp_path, env, expected):
    ini = tmp_path / "settings.ini"
    ini.write_text("[ServerSettings]\nServerAdminPassword=ini%password\nRCONPort=27031\n")
    settings = AsaSettings({**env, "ASA_GAME_USER_SETTINGS_PATH": str(ini)})
    assert settings.rcon_endpoint() == expected


def test_strict_rcon_endpoint_never_tries_fallback_password(tmp_path):
    settings = AsaSettings({"ASA_REQUIRE_ADMIN_PASSWORD": "true",
                            "ASA_GAME_USER_SETTINGS_PATH": str(tmp_path / "absent")})
    with pytest.raises(RconPasswordNotFoundError):
        settings.rcon_endpoint()


@pytest.mark.parametrize("port", ["non-numeric", "0", "65536"])
def test_managed_rcon_endpoint_rejects_invalid_port(port):
    settings = AsaSettings({"ASA_RCON_PORT": port})
    with pytest.raises(RconPortNotFoundError):
        settings.rcon_endpoint()
