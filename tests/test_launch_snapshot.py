"""Shutdown discovery must use the configuration actually launched."""

from asa_ctrl.common.config import AsaSettings
from asa_ctrl.common.launch_config import LaunchConfiguration, discrete_env_vars
from server_runtime.constants import RuntimeSettings
from server_runtime.launch_env import LaunchEnvironment
from server_runtime.supervisor import ServerSupervisor


def test_rotated_secret_does_not_change_shutdown_credentials(tmp_path, monkeypatch):
    secret = tmp_path / "admin-password"
    secret.write_text("original-password\n", encoding="utf-8")
    source = {
        "ASA_SERVER_ADMIN_PASSWORD_FILE": str(secret),
        "ASA_RCON_PORT": "27021",
        "ASA_MAP": "TheIsland_WP",
        "ASA_EXTRA_FLAGS": "-mods=123",
        "ASA_LOG_LEVEL": "DEBUG",
    }
    line = LaunchConfiguration.from_env(source).render()
    monkeypatch.setattr("server_runtime.launch_env._resolve_runtime_dir", lambda base: str(tmp_path))
    env = LaunchEnvironment(source, RuntimeSettings.from_env({})).for_server(line)
    secret.write_text("rotated-password\n", encoding="utf-8")

    supervisor = object.__new__(ServerSupervisor)
    supervisor.server_env = env
    shutdown = supervisor._rcon_settings()
    assert shutdown.get_start_param_value("ServerAdminPassword") == "original-password"
    assert shutdown.get_start_param_value("RCONPort") == "27021"
    assert env["ASA_START_PARAMS"] == line
    assert all(name not in env for name in discrete_env_vars())
    assert env["ASA_LOG_LEVEL"] == "DEBUG"
    assert source["ASA_SERVER_ADMIN_PASSWORD_FILE"] == str(secret)
    assert AsaSettings(source).get_start_param_value("ServerAdminPassword") == "rotated-password"


def test_disappearing_secret_does_not_break_shutdown_discovery(tmp_path, monkeypatch):
    secret = tmp_path / "admin-password"
    secret.write_text("original-password", encoding="utf-8")
    source = {"ASA_SERVER_ADMIN_PASSWORD_FILE": str(secret)}
    line = LaunchConfiguration.from_env(source).render()
    monkeypatch.setattr("server_runtime.launch_env._resolve_runtime_dir", lambda base: str(tmp_path))
    env = LaunchEnvironment(source, RuntimeSettings.from_env({})).for_server(line)
    secret.unlink()
    assert AsaSettings(env).get_start_param_value("ServerAdminPassword") == "original-password"


def test_environment_without_resolved_line_keeps_overlay_inputs(tmp_path, monkeypatch):
    source = {"ASA_SERVER_ADMIN_PASSWORD_FILE": "/run/secrets/password", "ASA_MAP": "Map"}
    monkeypatch.setattr("server_runtime.launch_env._resolve_runtime_dir", lambda base: str(tmp_path))
    env = LaunchEnvironment(source, RuntimeSettings.from_env({})).for_server()
    assert env["ASA_SERVER_ADMIN_PASSWORD_FILE"] == source["ASA_SERVER_ADMIN_PASSWORD_FILE"]
    assert env["ASA_MAP"] == "Map"
