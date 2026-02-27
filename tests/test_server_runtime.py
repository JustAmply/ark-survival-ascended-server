from __future__ import annotations

import logging
import os
import signal
import tarfile
from unittest.mock import Mock

import pytest

from server_runtime import logging_utils as runtime_logging
from server_runtime import params as runtime_params
from server_runtime import permissions as runtime_permissions
from server_runtime import proton as runtime_proton
from server_runtime import steamcmd as runtime_steamcmd
from server_runtime.archive_utils import safe_extract_tar
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


def test_shutdown_sequence_skips_delay_when_saveworld_fails(monkeypatch):
    logger = logging.getLogger("test-shutdown")
    settings = RuntimeSettings.from_env()
    supervisor = ServerSupervisor(settings, logger)

    class DummyProcess:
        pid = 4242

        @staticmethod
        def poll():
            return None

    supervisor.server_process = DummyProcess()
    sleep_calls = []

    monkeypatch.setattr("server_runtime.supervisor.send_saveworld", lambda _logger: False)
    monkeypatch.setattr("server_runtime.supervisor.time.sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr("server_runtime.supervisor.stop_server_process", lambda *_args, **_kwargs: None)

    supervisor._perform_shutdown_sequence(signal.SIGTERM, "container shutdown")

    assert sleep_calls == []


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


def test_safe_extract_tar_rejects_link_targets_outside_destination(tmp_path):
    archive = tmp_path / "archive.tar"
    with tarfile.open(archive, "w") as tar:
        link = tarfile.TarInfo("link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/tmp"
        tar.addfile(link)

    with tarfile.open(archive, "r") as tar:
        with pytest.raises(RuntimeError, match="Unsafe tar link target detected"):
            safe_extract_tar(tar, tmp_path / "extract")


def test_configure_runtime_logging_warn_alias(monkeypatch):
    monkeypatch.setenv("ASA_LOG_LEVEL", "warn")

    calls = {}
    monkeypatch.setattr(runtime_logging.logging, "basicConfig", lambda **kwargs: calls.update(kwargs))
    logger = Mock()
    real_get_logger = runtime_logging.logging.getLogger

    def fake_get_logger(name=None):
        if name == "server_runtime":
            return logger
        return real_get_logger(name)

    monkeypatch.setattr(runtime_logging.logging, "getLogger", fake_get_logger)

    resolved = runtime_logging.configure_runtime_logging()

    assert resolved is logger
    assert calls["level"] == logging.WARNING
    logger.warning.assert_not_called()


def test_cleanup_after_run_terminates_server_process(monkeypatch):
    logger = logging.getLogger("test-cleanup")
    settings = RuntimeSettings.from_env()
    supervisor = ServerSupervisor(settings, logger)
    process = Mock()
    supervisor.server_process = process

    kill_calls = []
    monkeypatch.setattr("server_runtime.supervisor.safe_kill_process", lambda proc: kill_calls.append(proc))

    supervisor._cleanup_after_run()

    assert kill_calls == [process]
    assert supervisor.server_process is None


def test_safe_extract_tar_allows_symlink_targets_within_destination(tmp_path):
    class DummyTar:
        def __init__(self, members):
            self._members = members
            self.extract_calls = []

        def getmembers(self):
            return self._members

        def extractall(self, destination, members):
            self.extract_calls.append((destination, members))

    link = tarfile.TarInfo("plugins/link")
    link.type = tarfile.SYMTYPE
    link.linkname = "../target.dll"

    archive = DummyTar([link])
    safe_extract_tar(archive, tmp_path / "extract")

    assert len(archive.extract_calls) == 1


def test_safe_extract_tar_rejects_hardlink_targets_outside_destination(tmp_path):
    archive = tmp_path / "archive-hardlink.tar"
    with tarfile.open(archive, "w") as tar:
        hardlink = tarfile.TarInfo("hardlink")
        hardlink.type = tarfile.LNKTYPE
        hardlink.linkname = "../outside"
        tar.addfile(hardlink)

    with tarfile.open(archive, "r") as tar:
        with pytest.raises(RuntimeError, match="Unsafe tar link target detected"):
            safe_extract_tar(tar, tmp_path / "extract")


def test_prepare_runtime_env_falls_back_when_xdg_runtime_dir_is_file(monkeypatch, tmp_path):
    logger = logging.getLogger("test-runtime-env")
    supervisor = ServerSupervisor(RuntimeSettings.from_env(), logger)
    xdg_file = tmp_path / "xdg-runtime-file"
    xdg_file.write_text("broken", encoding="utf-8")
    mkdir_calls = []

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(xdg_file))
    monkeypatch.setattr("server_runtime.supervisor.os.getuid", lambda: 12345, raising=False)
    monkeypatch.setattr("server_runtime.supervisor.os.access", lambda _path, _mode: True)
    monkeypatch.setattr(
        "server_runtime.supervisor.Path.mkdir",
        lambda self, parents=True, exist_ok=True: mkdir_calls.append(str(self)),
    )
    monkeypatch.setattr("server_runtime.supervisor.os.chmod", lambda *_args, **_kwargs: None)

    supervisor._prepare_runtime_env()

    assert os.environ["XDG_RUNTIME_DIR"] == "/tmp/xdg-runtime-12345"
    assert any(path.replace("\\", "/") == "/tmp/xdg-runtime-12345" for path in mkdir_calls)


def test_ensure_steamcmd_reinstalls_when_linux32_is_file(monkeypatch, tmp_path):
    steamcmd_dir = tmp_path / "steamcmd"
    steamcmd_dir.mkdir(parents=True, exist_ok=True)
    (steamcmd_dir / "linux32").write_text("stale", encoding="utf-8")

    calls = {"url": "", "extract": 0}

    class DummyResponse:
        def __init__(self):
            self._chunks = [b"not-a-real-tar", b""]

        def read(self, _size):
            return self._chunks.pop(0)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class DummyTar:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(url, timeout=30):
        calls["url"] = url
        return DummyResponse()

    def fake_extract(_tar, _destination):
        calls["extract"] += 1

    monkeypatch.setattr(runtime_steamcmd, "STEAMCMD_DIR", str(steamcmd_dir))
    monkeypatch.setattr(runtime_steamcmd.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(runtime_steamcmd.tarfile, "open", lambda *_args, **_kwargs: DummyTar())
    monkeypatch.setattr(runtime_steamcmd, "safe_extract_tar", fake_extract)

    runtime_steamcmd.ensure_steamcmd(logging.getLogger("test-steamcmd"))

    assert "steamcmd_linux.tar.gz" in calls["url"]
    assert calls["extract"] == 1


def test_inject_mods_param_ignores_nonzero_exit(monkeypatch):
    logger = logging.getLogger("test")
    monkeypatch.setenv("ASA_START_PARAMS", "Map?listen")
    result = Mock(returncode=1, stdout="-mods=1,2", stderr="error")
    monkeypatch.setattr(runtime_params.subprocess, "run", lambda *args, **kwargs: result)

    merged = runtime_params.inject_mods_param("Map?listen", logger)

    assert merged == "Map?listen"
    assert os.environ["ASA_START_PARAMS"] == "Map?listen"


def test_verify_sha512_requires_exact_filename_match(tmp_path):
    archive = tmp_path / "GE-Proton9-2.tar.gz"
    archive.write_bytes(b"abc123")
    import hashlib

    digest = hashlib.sha512(b"abc123").hexdigest()
    checksum = tmp_path / "GE-Proton9-2.sha512sum"
    checksum.write_text(f"{digest}  GE-Proton9-20.tar.gz\n", encoding="utf-8")

    assert runtime_proton._verify_sha512(archive, checksum) is False


def test_scheduler_contract_defaults_warnings_when_empty(monkeypatch):
    monkeypatch.setenv("SERVER_RESTART_CRON", "0 4 * * *")
    monkeypatch.setenv("SERVER_RESTART_WARNINGS", "")
    logger = logging.getLogger("test")
    settings = RuntimeSettings.from_env()
    supervisor = ServerSupervisor(settings, logger)

    class DummyProcess:
        pid = 999

        @staticmethod
        def poll():
            return None

    monkeypatch.setattr(os.path, "isfile", lambda path: True)
    monkeypatch.setattr(os, "access", lambda path, mode: True)
    monkeypatch.setattr("server_runtime.supervisor.ASA_CTRL_BIN", "/usr/local/bin/asa-ctrl")
    monkeypatch.setattr("server_runtime.supervisor.subprocess.Popen", lambda *args, **kwargs: DummyProcess())

    supervisor.start_restart_scheduler()

    assert os.environ["SERVER_RESTART_WARNINGS"] == "30,5,1"


def test_chown_path_uses_no_symlink_follow(monkeypatch, tmp_path):
    calls = []

    def fake_chown(path, user=None, group=None, follow_symlinks=True):
        calls.append({
            "path": path,
            "user": user,
            "group": group,
            "follow_symlinks": follow_symlinks,
        })

    monkeypatch.setattr(runtime_permissions.shutil, "chown", fake_chown)

    runtime_permissions._chown_path(tmp_path)

    assert calls[0]["follow_symlinks"] is False
