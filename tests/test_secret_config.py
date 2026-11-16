"""Secret-file launch overlays and explicit admin-password enforcement."""

import logging

import pytest

from asa_ctrl.common.config import AsaSettings
from asa_ctrl.common.errors import ConfigurationError
from asa_ctrl.common.launch_config import LaunchConfiguration
from asa_ctrl.core.rcon import RconClient
from server_runtime.constants import RuntimeSettings
from server_runtime.params import prepare_start_params


@pytest.mark.parametrize("name,key", [
    ("ASA_SERVER_ADMIN_PASSWORD", "ServerAdminPassword"),
    ("ASA_SERVER_PASSWORD", "ServerPassword"),
    ("ASA_SPECTATOR_PASSWORD", "SpectatorPassword"),
])
def test_secret_overlay_is_shared_with_settings_and_redacted(tmp_path, name, key):
    secret = tmp_path / "password"
    secret.write_text("private-123\n", encoding="utf-8")
    env = {f"{name}_FILE": str(secret)}
    config = AsaSettings(env).launch_configuration()
    assert config.value(key) == "private-123"
    assert LaunchConfiguration.parse(config.render()).value(key) == "private-123"
    assert "private-123" not in config.render_for_logging()
    assert name not in env


def test_secret_precedence_preserves_extras(tmp_path):
    secret = tmp_path / "password"
    secret.write_text("file-password", encoding="utf-8")
    config = LaunchConfiguration.from_env({
        "ASA_START_PARAMS": "Map?ServerAdminPassword=legacy",
        "ASA_SERVER_ADMIN_PASSWORD_FILE": str(secret),
        "ASA_EXTRA_QUERY_PARAMS": "ServerAdminPassword=extra",
    })
    assert config.value("ServerAdminPassword") == "extra"


def test_rcon_discovers_file_password(tmp_path):
    secret = tmp_path / "password"
    secret.write_text("file-password\n", encoding="utf-8")
    client = RconClient(settings=AsaSettings({"ASA_SERVER_ADMIN_PASSWORD_FILE": str(secret)}))
    assert client.password == "file-password"
    assert client.port == 27020


@pytest.mark.parametrize("direct", ["", "direct-password"])
def test_direct_and_file_are_ambiguous_even_when_direct_is_empty(tmp_path, direct):
    with pytest.raises(ConfigurationError, match="either ASA_SERVER_ADMIN_PASSWORD"):
        LaunchConfiguration.from_env({
            "ASA_SERVER_ADMIN_PASSWORD": direct,
            "ASA_SERVER_ADMIN_PASSWORD_FILE": str(tmp_path / "missing"),
        })


@pytest.mark.parametrize("content", [b"", b"\n", b"secret?Port=1", b"secret with space", b"secret\nother", b"secret'", b"secret\\", b"\xff", b"secret\0"])
def test_invalid_secret_fails_without_exposing_contents(tmp_path, content):
    secret = tmp_path / "password"
    secret.write_bytes(content)
    with pytest.raises(ConfigurationError) as error:
        LaunchConfiguration.from_env({"ASA_SERVER_ADMIN_PASSWORD_FILE": str(secret)})
    assert "secret?Port=1" not in str(error.value)
    assert "secret with space" not in str(error.value)
    assert str(secret) not in str(error.value)


@pytest.mark.parametrize("path", ["", "missing"])
def test_unreadable_secret_is_not_a_missing_password_fallback(tmp_path, path):
    value = str(tmp_path / path) if path else ""
    with pytest.raises(ConfigurationError):
        LaunchConfiguration.from_env({"ASA_SERVER_ADMIN_PASSWORD_FILE": value})


@pytest.fixture
def runtime_environment(monkeypatch, tmp_path):
    from asa_ctrl.common.launch_config import discrete_env_vars

    for name in (*discrete_env_vars(), "ASA_START_PARAMS", "ASA_REQUIRE_ADMIN_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ASA_MOD_DATABASE_PATH", str(tmp_path / "mods.json"))
    monkeypatch.setenv("ASA_GAME_USER_SETTINGS_PATH", str(tmp_path / "GameUserSettings.ini"))
    return tmp_path


@pytest.mark.parametrize("line", ["", "Map?listen"])
def test_strict_mode_rejects_missing_password_before_mod_database_creation(runtime_environment, monkeypatch, line):
    monkeypatch.setenv("ASA_START_PARAMS", line)
    monkeypatch.setenv("ASA_REQUIRE_ADMIN_PASSWORD", "true")
    with pytest.raises(ConfigurationError, match="no ServerAdminPassword"):
        prepare_start_params(logging.getLogger("test-secrets"))
    assert not (runtime_environment / "mods.json").exists()


def test_strict_mode_accepts_ini_password_with_default_map(runtime_environment, monkeypatch):
    (runtime_environment / "GameUserSettings.ini").write_text(
        "[ServerSettings]\nServerAdminPassword=ini-password\n", encoding="utf-8"
    )
    params = prepare_start_params(
        logging.getLogger("test-secrets"),
        RuntimeSettings.from_env({"ASA_REQUIRE_ADMIN_PASSWORD": "1"}),
    )
    assert params.startswith("TheIsland_WP?")
    assert "changeme" not in params


def test_strict_mode_accepts_secret_file(runtime_environment, monkeypatch):
    secret = runtime_environment / "password"
    secret.write_text("file-password\n", encoding="utf-8")
    monkeypatch.setenv("ASA_SERVER_ADMIN_PASSWORD_FILE", str(secret))
    monkeypatch.setenv("ASA_REQUIRE_ADMIN_PASSWORD", "1")
    params = prepare_start_params(logging.getLogger("test-secrets"))
    assert LaunchConfiguration.parse(params).value("ServerAdminPassword") == "file-password"


def test_default_mode_retains_legacy_fallback(runtime_environment):
    params = prepare_start_params(logging.getLogger("test-secrets"))
    assert LaunchConfiguration.parse(params).value("ServerAdminPassword") == "changeme"
