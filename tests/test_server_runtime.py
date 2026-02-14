from __future__ import annotations

import logging
import os
from unittest.mock import Mock

import pytest

from server_runtime import logging_utils as runtime_logging
from server_runtime import params as runtime_params
from server_runtime import permissions as runtime_permissions
from server_runtime import proton as runtime_proton
from server_runtime.constants import RuntimeSettings
from server_runtime.supervisor import ServerSupervisor


def test_runtime_settings_defaults(monkeypatch):
    monkeypatch.delenv("ENABLE_DEBUG", raising=False)
    monkeypatch.delenv("SERVER_RESTART_DELAY", raising=False)
    monkeypatch.delenv("ASA_SHUTDOWN_SAVEWORLD_DELAY", raising=False)
    monkeypatch.delenv("ASA_SHUTDOWN_TIMEOUT", raising=False)

    settings = RuntimeSettings.from_env()
    assert settings.enable_debug is False
    assert settings.server_restart_delay == 15
    assert settings.shutdown_saveworld_delay == 15
    assert settings.shutdown_timeout == 180


def test_server_admin_password_fallback_when_missing(monkeypatch):
    monkeypatch.setenv("ASA_START_PARAMS", "TheIsland_WP?listen?Port=7777")
    monkeypatch.setattr(runtime_params, "server_admin_password_in_ini", lambda: False)
    logger = logging.getLogger("test")

    params = runtime_params.ensure_server_admin_password(logger)
    assert "ServerAdminPassword=changeme" in params
    assert "ServerAdminPassword=changeme" in os.environ["ASA_START_PARAMS"]


def test_server_admin_password_default_payload_when_empty(monkeypatch):
    monkeypatch.delenv("ASA_START_PARAMS", raising=False)
    monkeypatch.setattr(runtime_params, "server_admin_password_in_ini", lambda: False)
    logger = logging.getLogger("test")

    params = runtime_params.ensure_server_admin_password(logger)
    assert params.startswith("TheIsland_WP?")
    assert "ServerAdminPassword=changeme" in params


def test_ensure_nosteam_flag_idempotent(monkeypatch):
    monkeypatch.setenv("ASA_START_PARAMS", "Map?listen -flag")
    first = runtime_params.ensure_nosteam_flag(os.environ["ASA_START_PARAMS"])
    second = runtime_params.ensure_nosteam_flag(first)

    assert first.endswith("-nosteam")
    assert second == first
    assert second.count("-nosteam") == 1


def test_inject_mods_param(monkeypatch):
    logger = logging.getLogger("test")
    result = Mock(returncode=0, stdout="-mods=1,2", stderr="")
    monkeypatch.setattr(runtime_params.subprocess, "run", lambda *args, **kwargs: result)

    merged = runtime_params.inject_mods_param("Map?listen", logger)
    assert merged.endswith("-mods=1,2")


def test_inject_mods_param_empty(monkeypatch):
    logger = logging.getLogger("test")
    result = Mock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(runtime_params.subprocess, "run", lambda *args, **kwargs: result)

    merged = runtime_params.inject_mods_param("Map?listen", logger)
    assert merged == "Map?listen"


def test_resolve_proton_version_detected_latest(monkeypatch):
    monkeypatch.delenv("PROTON_VERSION", raising=False)
    monkeypatch.setattr(
        runtime_proton,
        "_fetch_json",
        lambda _url: {"tag_name": "GE-Proton9-20"},
    )
    monkeypatch.setattr(runtime_proton, "_check_release_assets", lambda _version: True)
    logger = logging.getLogger("test")

    version = runtime_proton.resolve_proton_version(logger)
    assert version == "9-20"
    assert os.environ["PROTON_VERSION"] == "9-20"


def test_resolve_proton_version_fallback(monkeypatch):
    monkeypatch.delenv("PROTON_VERSION", raising=False)
    monkeypatch.setattr(runtime_proton, "_fetch_json", lambda _url: None)
    monkeypatch.setattr(runtime_proton, "find_latest_release_with_assets", lambda skip_version=None: None)
    logger = logging.getLogger("test")

    version = runtime_proton.resolve_proton_version(logger)
    assert version == runtime_proton.FALLBACK_PROTON_VERSION


def test_verify_sha512_ok(tmp_path):
    archive = tmp_path / "GE-ProtonX.tar.gz"
    archive.write_bytes(b"abc123")
    import hashlib

    digest = hashlib.sha512(b"abc123").hexdigest()
    checksum = tmp_path / "GE-ProtonX.sha512sum"
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")

    assert runtime_proton._verify_sha512(archive, checksum) is True


def test_scheduler_contract_exports_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SERVER_RESTART_CRON", "0 4 * * *")
    monkeypatch.delenv("SERVER_RESTART_WARNINGS", raising=False)
    monkeypatch.setattr(runtime_params, "GAME_USER_SETTINGS_PATH", str(tmp_path / "GameUserSettings.ini"))
    logger = logging.getLogger("test")
    settings = RuntimeSettings.from_env()
    supervisor = ServerSupervisor(settings, logger)

    calls = {}

    class DummyProcess:
        pid = 999

        @staticmethod
        def poll():
            return None

    def fake_popen(command, *args, **kwargs):
        calls["command"] = command
        return DummyProcess()

    monkeypatch.setattr(os.path, "isfile", lambda path: True)
    monkeypatch.setattr(os, "access", lambda path, mode: True)
    monkeypatch.setattr("server_runtime.supervisor.ASA_CTRL_BIN", "/usr/local/bin/asa-ctrl")
    monkeypatch.setattr("server_runtime.supervisor.subprocess.Popen", fake_popen)
    supervisor.start_restart_scheduler()

    assert calls["command"] == ["/usr/local/bin/asa-ctrl", "restart-scheduler"]
    assert os.environ["ASA_SUPERVISOR_PID_FILE"]
    assert os.environ["ASA_SERVER_PID_FILE"]
    assert os.environ["SERVER_RESTART_WARNINGS"] == "30,5,1"


def test_configure_runtime_logging_invalid_level_warns(monkeypatch, caplog):
    monkeypatch.setenv("ASA_LOG_LEVEL", "VERBOSE")
    caplog.set_level(logging.WARNING, logger="server_runtime")

    logger = runtime_logging.configure_runtime_logging()

    assert logger is logging.getLogger("server_runtime")
    assert "Invalid ASA_LOG_LEVEL" in caplog.text


def test_drop_privileges_reports_exec_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_permissions.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.delenv(runtime_permissions.PRIVS_DROPPED_ENV, raising=False)
    monkeypatch.setattr(runtime_permissions, "STEAM_HOME_DIR", str(tmp_path / "steam"))
    monkeypatch.setattr(runtime_permissions, "STEAMCMD_DIR", str(tmp_path / "steamcmd"))
    monkeypatch.setattr(runtime_permissions, "SERVER_FILES_DIR", str(tmp_path / "server"))
    monkeypatch.setattr(runtime_permissions, "CLUSTER_DIR", str(tmp_path / "cluster"))
    monkeypatch.setattr(runtime_permissions, "_chown_if_possible", lambda _path, recursive: None)
    monkeypatch.setattr(runtime_permissions.shutil, "which", lambda cmd: "/usr/sbin/runuser" if cmd == "runuser" else None)
    monkeypatch.setattr(
        runtime_permissions.os,
        "execvp",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("permission denied")),
    )

    with pytest.raises(RuntimeError, match="Failed to drop privileges"):
        runtime_permissions.ensure_permissions_and_drop_privileges(logging.getLogger("test"))


def test_supervisor_run_restarts_after_launch_exception(monkeypatch, caplog):
    logger = logging.getLogger("test-supervisor")
    settings = RuntimeSettings.from_env()
    supervisor = ServerSupervisor(settings, logger)
    attempts = {"count": 0}

    def fake_launch():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("boom")
        supervisor.supervisor_exit_requested = True
        return 0

    monkeypatch.setattr(supervisor, "_launch_server_once", fake_launch)
    monkeypatch.setattr("server_runtime.supervisor.time.sleep", lambda _seconds: None)
    caplog.set_level(logging.ERROR)

    code = supervisor.run()

    assert code == 0
    assert attempts["count"] == 2
    assert "Unhandled exception during server run" in caplog.text
