import pytest

from asa_ctrl.cli import main
from asa_ctrl.common.config import AsaSettings
from asa_ctrl.common.constants import ExitCodes


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
