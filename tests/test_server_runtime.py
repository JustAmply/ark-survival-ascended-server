from __future__ import annotations

import logging
import os
import signal
import stat
import subprocess
import tarfile
import zipfile
from unittest.mock import Mock

import pytest

from asa_ctrl.common import launch_config
from server_runtime import bootstrap as runtime_bootstrap
from server_runtime import logging_utils as runtime_logging
from server_runtime import native_libs as runtime_native_libs
from server_runtime import params as runtime_params
from server_runtime import permissions as runtime_permissions
from server_runtime import proton as runtime_proton
from server_runtime import steamcmd as runtime_steamcmd
from server_runtime import supervisor as runtime_supervisor
from server_runtime import wine_sync as runtime_wine_sync
from server_runtime.archive_utils import safe_extract_archive
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


def test_runtime_settings_read_from_a_plain_mapping():
    """The whole runtime contract resolves without touching os.environ."""
    settings = RuntimeSettings.from_env(
        {
            "ENABLE_DEBUG": "yes",
            "SERVER_RESTART_CRON": " 0 4 * * * ",
            "SERVER_RESTART_WARNINGS": "60,10",
            "SERVER_RESTART_DELAY": "30",
            "ASA_SHUTDOWN_SAVEWORLD_DELAY": "5",
            "ASA_SHUTDOWN_TIMEOUT": "not-a-number",
            "PROTON_VERSION": "9-20",
            "PROTON_SKIP_CHECKSUM": "1",
            "ASA_LOG_LEVEL": "debug",
            "TZ": "Europe/Berlin",
        }
    )

    assert settings.enable_debug is True
    assert settings.server_restart_cron == "0 4 * * *"
    assert settings.restart_warnings_or_default() == "60,10"
    assert settings.server_restart_delay == 30
    assert settings.shutdown_saveworld_delay == 5
    assert settings.shutdown_timeout == 180  # falls back on garbage
    assert settings.proton_version == "9-20"
    assert settings.proton_skip_checksum is True
    assert settings.log_level == "DEBUG"
    assert settings.timezone == "Europe/Berlin"


def test_runtime_settings_restart_warnings_default():
    assert RuntimeSettings.from_env({}).restart_warnings_or_default() == "30,5,1"


def test_main_preserves_startup_order_and_cleans_up_after_failure(monkeypatch):
    events = []
    logger = logging.getLogger("test-main-lifecycle")

    monkeypatch.setattr(
        runtime_supervisor, "configure_runtime_logging", lambda settings=None: logger
    )
    monkeypatch.setattr(runtime_supervisor.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(
        runtime_supervisor,
        "configure_timezone",
        lambda _logger: events.append("configure_timezone"),
    )
    monkeypatch.setattr(
        runtime_supervisor,
        "ensure_machine_id",
        lambda _logger: events.append("ensure_machine_id"),
    )
    monkeypatch.setattr(
        runtime_supervisor,
        "maybe_debug_hold",
        lambda _enabled, _logger: events.append("maybe_debug_hold"),
    )
    monkeypatch.setattr(
        runtime_supervisor,
        "ensure_permissions_and_drop_privileges",
        lambda _logger: events.append("drop_privileges"),
    )
    monkeypatch.setattr(
        runtime_supervisor,
        "ensure_steamcmd",
        lambda _logger: events.append("ensure_steamcmd"),
    )

    class RecordingSupervisor:
        def __init__(self, _settings, _logger):
            events.append("create_supervisor")

        def register_supervisor_pid(self):
            events.append("register_supervisor_pid")

        def start_restart_scheduler(self):
            events.append("start_restart_scheduler")

        def run(self):
            events.append("run_supervisor")
            raise RuntimeError("launch failed")

        def cleanup(self):
            events.append("cleanup")

    monkeypatch.setattr(runtime_supervisor, "ServerSupervisor", RecordingSupervisor)

    with pytest.raises(RuntimeError, match="launch failed"):
        runtime_supervisor.main()

    assert events == [
        "configure_timezone",
        "ensure_machine_id",
        "maybe_debug_hold",
        "drop_privileges",
        "ensure_steamcmd",
        "create_supervisor",
        "register_supervisor_pid",
        "start_restart_scheduler",
        "run_supervisor",
        "cleanup",
    ]


def test_prepare_start_params_applies_complete_contract(monkeypatch, tmp_path):
    mods_path = tmp_path / "mods.json"
    mods_path.write_text(
        '[{"mod_id": 1, "enabled": true}, {"mod_id": 2, "enabled": true}]',
        encoding="utf-8",
    )
    monkeypatch.setenv("ASA_START_PARAMS", "TheIsland_WP?listen?Port=7777")
    monkeypatch.setenv("ASA_MOD_DATABASE_PATH", str(mods_path))
    monkeypatch.setenv("ASA_GAME_USER_SETTINGS_PATH", str(tmp_path / "missing.ini"))
    logger = logging.getLogger("test")

    params = runtime_params.prepare_start_params(logger)

    assert "ServerAdminPassword=changeme" in params
    assert params.endswith("-mods=1,2 -nosteam")
    assert os.environ["ASA_START_PARAMS"] == params


def test_prepare_start_params_uses_default_payload_when_empty(monkeypatch, tmp_path):
    monkeypatch.delenv("ASA_START_PARAMS", raising=False)
    monkeypatch.setenv("ASA_MOD_DATABASE_PATH", str(tmp_path / "mods.json"))
    monkeypatch.setenv("ASA_GAME_USER_SETTINGS_PATH", str(tmp_path / "missing.ini"))
    logger = logging.getLogger("test")

    params = runtime_params.prepare_start_params(logger)

    assert params.startswith("TheIsland_WP?")
    assert "ServerAdminPassword=changeme" in params
    assert params.endswith("-nosteam")


def test_prepare_start_params_preserves_ini_password_and_nosteam(monkeypatch, tmp_path):
    ini_path = tmp_path / "GameUserSettings.ini"
    ini_path.write_text("[ServerSettings]\nServerAdminPassword=secret\n", encoding="utf-8")
    monkeypatch.setenv("ASA_GAME_USER_SETTINGS_PATH", str(ini_path))
    monkeypatch.setenv("ASA_MOD_DATABASE_PATH", str(tmp_path / "mods.json"))
    monkeypatch.setenv("ASA_START_PARAMS", "Map?listen -nosteam")
    logger = logging.getLogger("test")

    params = runtime_params.prepare_start_params(logger)

    assert "ServerAdminPassword=changeme" not in params
    assert params.count("-nosteam") == 1


def test_prepare_start_params_skips_corrupt_mod_database(monkeypatch, tmp_path, caplog):
    mods_path = tmp_path / "mods.json"
    mods_path.write_text("not-json", encoding="utf-8")
    monkeypatch.setenv("ASA_MOD_DATABASE_PATH", str(mods_path))
    monkeypatch.setenv("ASA_GAME_USER_SETTINGS_PATH", str(tmp_path / "missing.ini"))
    monkeypatch.setenv("ASA_START_PARAMS", "Map?listen?ServerAdminPassword=secret")
    logger = logging.getLogger("test")

    params = runtime_params.prepare_start_params(logger)

    assert params == "Map?listen?ServerAdminPassword=secret -nosteam"
    assert "skipping mods injection" in caplog.text


def test_prepare_start_params_merges_mods_into_an_existing_flag(monkeypatch, tmp_path):
    """A -mods= flag in the start params must not be duplicated by mods.json."""
    mods_path = tmp_path / "mods.json"
    mods_path.write_text('[{"mod_id": 900, "enabled": true}]', encoding="utf-8")
    monkeypatch.setenv("ASA_START_PARAMS", "Map?listen?ServerAdminPassword=x -mods=100,200")
    monkeypatch.setenv("ASA_MOD_DATABASE_PATH", str(mods_path))
    monkeypatch.setenv("ASA_GAME_USER_SETTINGS_PATH", str(tmp_path / "missing.ini"))
    logger = logging.getLogger("test")

    params = runtime_params.prepare_start_params(logger)

    assert params == "Map?listen?ServerAdminPassword=x -mods=100,200,900 -nosteam"
    assert params.count("-mods=") == 1


def _clear_launch_env(monkeypatch):
    for name in launch_config.LAUNCH_ENV_VARS + ("ASA_START_PARAMS",):
        monkeypatch.delenv(name, raising=False)


def test_prepare_start_params_from_discrete_env_only(monkeypatch, tmp_path):
    _clear_launch_env(monkeypatch)
    monkeypatch.setenv("ASA_MAP", "Ragnarok_WP")
    monkeypatch.setenv("ASA_PORT", "7778")
    monkeypatch.setenv("ASA_RCON_PORT", "27021")
    monkeypatch.setenv("ASA_SERVER_ADMIN_PASSWORD", "s3cret")
    monkeypatch.setenv("ASA_MAX_PLAYERS", "70")
    monkeypatch.setenv("ASA_CLUSTER_ID", "mycluster")
    monkeypatch.setenv("ASA_MOD_DATABASE_PATH", str(tmp_path / "mods.json"))
    monkeypatch.setenv("ASA_GAME_USER_SETTINGS_PATH", str(tmp_path / "missing.ini"))
    logger = logging.getLogger("test")

    params = runtime_params.prepare_start_params(logger)

    assert params == (
        "Ragnarok_WP?listen?Port=7778?RCONPort=27021?RCONEnabled=True"
        "?ServerAdminPassword=s3cret -WinLiveMaxPlayers=70 -clusterid=mycluster -nosteam"
    )


def test_prepare_start_params_discrete_env_overlays_legacy_line(monkeypatch, tmp_path):
    """Existing stacks keep their line; a single knob can still be overridden."""
    _clear_launch_env(monkeypatch)
    monkeypatch.setenv(
        "ASA_START_PARAMS",
        "TheIsland_WP?listen?Port=7777?RCONPort=27020?ServerAdminPassword=old "
        "-WinLiveMaxPlayers=50",
    )
    monkeypatch.setenv("ASA_SERVER_ADMIN_PASSWORD", "rotated")
    monkeypatch.setenv("ASA_MOD_DATABASE_PATH", str(tmp_path / "mods.json"))
    monkeypatch.setenv("ASA_GAME_USER_SETTINGS_PATH", str(tmp_path / "missing.ini"))
    logger = logging.getLogger("test")

    params = runtime_params.prepare_start_params(logger)

    assert params == (
        "TheIsland_WP?listen?Port=7777?RCONPort=27020?ServerAdminPassword=rotated "
        "-WinLiveMaxPlayers=50 -nosteam"
    )


def test_prepare_start_params_leaves_legacy_line_untouched(monkeypatch, tmp_path):
    """No discrete variable set - the launch line must survive verbatim."""
    _clear_launch_env(monkeypatch)
    legacy = (
        "TheIsland_WP?listen?Port=7777?RCONPort=27020?RCONEnabled=True"
        "?ServerAdminPassword=change_this_password -WinLiveMaxPlayers=50 "
        '-clusterid=default -ClusterDirOverride="/home/gameserver/cluster-shared" '
        "-nosteam"
    )
    monkeypatch.setenv("ASA_START_PARAMS", legacy)
    monkeypatch.setenv("ASA_MOD_DATABASE_PATH", str(tmp_path / "mods.json"))
    monkeypatch.setenv("ASA_GAME_USER_SETTINGS_PATH", str(tmp_path / "missing.ini"))
    logger = logging.getLogger("test")

    assert runtime_params.prepare_start_params(logger) == legacy


def test_prepare_start_params_extra_flags_escape_hatch(monkeypatch, tmp_path):
    _clear_launch_env(monkeypatch)
    monkeypatch.setenv("ASA_START_PARAMS", "Map?listen?ServerAdminPassword=x")
    monkeypatch.setenv("ASA_EXTRA_FLAGS", "-servergamelog")
    monkeypatch.setenv("ASA_BATTLEYE", "false")
    monkeypatch.setenv("ASA_MOD_DATABASE_PATH", str(tmp_path / "mods.json"))
    monkeypatch.setenv("ASA_GAME_USER_SETTINGS_PATH", str(tmp_path / "missing.ini"))
    logger = logging.getLogger("test")

    params = runtime_params.prepare_start_params(logger)

    assert params == "Map?listen?ServerAdminPassword=x -NoBattlEye -servergamelog -nosteam"


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


def test_scheduler_contract_exports_env(monkeypatch):
    monkeypatch.setenv("SERVER_RESTART_CRON", "0 4 * * *")
    monkeypatch.delenv("SERVER_RESTART_WARNINGS", raising=False)
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

        def __init__(self):
            self.running = True
            self.terminated = False

        def poll(self):
            return None if self.running else 0

        def terminate(self):
            self.terminated = True
            self.running = False

    process = DummyProcess()
    supervisor.server_process = process
    sleep_calls = []

    monkeypatch.setattr(
        "server_runtime.supervisor.execute_rcon_command",
        lambda _command: (_ for _ in ()).throw(runtime_supervisor.AsaCtrlError("offline")),
    )
    monkeypatch.setattr("server_runtime.supervisor.time.sleep", lambda seconds: sleep_calls.append(seconds))

    supervisor._perform_shutdown_sequence(signal.SIGTERM, "container shutdown")

    assert sleep_calls == []
    assert process.terminated is True


def test_shutdown_sequence_saves_waits_then_terminates(monkeypatch):
    events = []
    supervisor = ServerSupervisor(
        RuntimeSettings.from_env({"ASA_SHUTDOWN_SAVEWORLD_DELAY": "3"}),
        logging.getLogger("test-shutdown-success"),
    )
    process = Mock(pid=4242)
    process.poll.return_value = None
    supervisor.server_process = process

    monkeypatch.setattr(runtime_supervisor, "execute_rcon_command", lambda command: events.append(command))
    monkeypatch.setattr(runtime_supervisor.time, "sleep", lambda seconds: events.append(("sleep", seconds)))
    monkeypatch.setattr(supervisor, "_stop_server_process", lambda current: events.append(("stop", current)))

    supervisor._perform_shutdown_sequence(signal.SIGTERM, "container shutdown")

    assert events == ["saveworld", ("sleep", 3), ("stop", process)]


def test_shutdown_escalates_to_sigkill_after_timeout(monkeypatch):
    supervisor = ServerSupervisor(
        RuntimeSettings.from_env({"ASA_SHUTDOWN_TIMEOUT": "2"}),
        logging.getLogger("test-shutdown-timeout"),
    )
    process = Mock(pid=4242)
    process.poll.return_value = None
    now = iter([0, 1, 2])
    monkeypatch.setattr(runtime_supervisor.time, "time", lambda: next(now))
    monkeypatch.setattr(runtime_supervisor.time, "sleep", lambda _: None)

    supervisor._stop_server_process(process)

    process.terminate.assert_called_once_with()
    process.kill.assert_called_once_with()


def test_supervisor_log_hides_password_but_launches_with_it(monkeypatch, tmp_path):
    params = "Map?ServerAdminPassword=runtime-secret?Port=7777 -nosteam"
    logger = Mock()
    supervisor = ServerSupervisor(RuntimeSettings.from_env({}), logger)
    process = Mock(pid=4242)
    process.wait.return_value = 0

    monkeypatch.setattr(runtime_supervisor, "update_server_files", lambda *_: None)
    monkeypatch.setattr(runtime_supervisor, "prepare_start_params", lambda *_: params)
    monkeypatch.setattr(runtime_supervisor, "prepare_proton", lambda *_: "GE-Proton")
    monkeypatch.setattr(runtime_supervisor, "ensure_proton_compat_data", lambda *_: None)
    monkeypatch.setattr(runtime_supervisor, "resolve_launch_binary", lambda *_: "ArkAscendedServer.exe")
    monkeypatch.setattr(runtime_supervisor, "PID_FILE", str(tmp_path / "server.pid"))
    monkeypatch.setattr(supervisor, "_prepare_runtime_env", lambda: None)
    monkeypatch.setattr(supervisor, "_start_log_streamer", lambda: None)
    monkeypatch.setattr(runtime_supervisor.subprocess, "Popen", Mock(return_value=process))

    assert supervisor._launch_server_once() == 0

    logged = " ".join(str(call) for call in logger.info.call_args_list)
    assert "ServerAdminPassword=<redacted>" in logged
    assert "runtime-secret" not in logged
    assert any(
        "ServerAdminPassword=runtime-secret" in arg
        for arg in runtime_supervisor.subprocess.Popen.call_args.args[0]
    )


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


def test_safe_extract_archive_rejects_tar_link_targets_outside_destination(tmp_path):
    archive = tmp_path / "archive.tar"
    with tarfile.open(archive, "w") as tar:
        link = tarfile.TarInfo("link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/tmp"
        tar.addfile(link)

    with tarfile.open(archive, "r") as tar:
        with pytest.raises(RuntimeError, match="Unsafe tar link target detected"):
            safe_extract_archive(tar, tmp_path / "extract")


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


def test_cleanup_terminates_all_owned_processes():
    logger = logging.getLogger("test-cleanup")
    settings = RuntimeSettings.from_env()
    supervisor = ServerSupervisor(settings, logger)
    processes = [Mock(), Mock(), Mock()]
    for process in processes:
        process.poll.return_value = None
    supervisor.server_process, supervisor.log_streamer_process, supervisor.restart_scheduler_process = processes

    supervisor.cleanup()

    for process in processes:
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=5)


def test_safe_extract_archive_allows_tar_symlink_targets_within_destination(tmp_path, monkeypatch):
    archive_path = tmp_path / "archive.tar"
    with tarfile.open(archive_path, "w") as archive:
        link = tarfile.TarInfo("plugins/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../target.dll"
        archive.addfile(link)

    with tarfile.open(archive_path, "r") as archive:
        extract_calls = []
        monkeypatch.setattr(
            archive,
            "extractall",
            lambda destination, members: extract_calls.append((destination, members)),
        )
        safe_extract_archive(archive, tmp_path / "extract")

    assert len(extract_calls) == 1


def test_safe_extract_archive_rejects_tar_hardlink_targets_outside_destination(tmp_path):
    archive = tmp_path / "archive-hardlink.tar"
    with tarfile.open(archive, "w") as tar:
        hardlink = tarfile.TarInfo("hardlink")
        hardlink.type = tarfile.LNKTYPE
        hardlink.linkname = "../outside"
        tar.addfile(hardlink)

    with tarfile.open(archive, "r") as tar:
        with pytest.raises(RuntimeError, match="Unsafe tar link target detected"):
            safe_extract_archive(tar, tmp_path / "extract")


def test_safe_extract_archive_rejects_zip_path_traversal(tmp_path):
    archive_path = tmp_path / "archive.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.txt", "unsafe")

    with zipfile.ZipFile(archive_path, "r") as archive:
        with pytest.raises(RuntimeError, match="Unsafe zip member path detected"):
            safe_extract_archive(archive, tmp_path / "extract")


def test_safe_extract_archive_extracts_regular_zip_members(tmp_path):
    archive_path = tmp_path / "archive.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("plugins/readme.txt", "safe")

    with zipfile.ZipFile(archive_path, "r") as archive:
        safe_extract_archive(archive, tmp_path / "extract")

    extracted = tmp_path / "extract" / "plugins" / "readme.txt"
    assert extracted.read_text(encoding="utf-8") == "safe"


def test_safe_extract_archive_rejects_zip_symlinks(tmp_path):
    archive_path = tmp_path / "archive.zip"
    link = zipfile.ZipInfo("plugins/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(link, "../outside")

    with zipfile.ZipFile(archive_path, "r") as archive:
        with pytest.raises(RuntimeError, match="Unsupported zip special member detected"):
            safe_extract_archive(archive, tmp_path / "extract")


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
    assert os.environ["SDL_VIDEODRIVER"] == "dummy"
    assert os.environ["SDL_AUDIODRIVER"] == "dummy"
    assert os.environ["XDG_SESSION_TYPE"] == "headless"


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
    monkeypatch.setattr(runtime_steamcmd, "safe_extract_archive", fake_extract)

    runtime_steamcmd.ensure_steamcmd(logging.getLogger("test-steamcmd"))

    assert "steamcmd_linux.tar.gz" in calls["url"]
    assert calls["extract"] == 1


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

def test_prepare_runtime_env_preserves_headless_env_overrides(monkeypatch, tmp_path):
    logger = logging.getLogger("test-runtime-env-overrides")
    supervisor = ServerSupervisor(RuntimeSettings.from_env(), logger)
    runtime_dir = tmp_path / "xdg-runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("SDL_VIDEODRIVER", "wayland")
    monkeypatch.setenv("SDL_AUDIODRIVER", "pulse")
    monkeypatch.setenv("XDG_SESSION_TYPE", "tty")
    monkeypatch.setattr("server_runtime.supervisor.os.getuid", lambda: 12345, raising=False)
    monkeypatch.setattr("server_runtime.supervisor.os.chmod", lambda *_args, **_kwargs: None)

    supervisor._prepare_runtime_env()

    assert os.environ["SDL_VIDEODRIVER"] == "wayland"
    assert os.environ["SDL_AUDIODRIVER"] == "pulse"
    assert os.environ["XDG_SESSION_TYPE"] == "tty"


def test_ensure_machine_id_creates_files(monkeypatch, tmp_path):
    etc_machine_id = tmp_path / "etc" / "machine-id"
    dbus_machine_id = tmp_path / "var" / "lib" / "dbus" / "machine-id"

    monkeypatch.setattr(runtime_bootstrap, "ETC_MACHINE_ID_PATH", str(etc_machine_id))
    monkeypatch.setattr(runtime_bootstrap, "DBUS_MACHINE_ID_PATH", str(dbus_machine_id))

    runtime_bootstrap.ensure_machine_id(logging.getLogger("test-machine-id"))

    machine_id = etc_machine_id.read_text(encoding="utf-8").strip()
    assert len(machine_id) == 32
    assert all(ch in "0123456789abcdef" for ch in machine_id)
    assert dbus_machine_id.exists()
    if dbus_machine_id.is_symlink():
        assert dbus_machine_id.resolve() == etc_machine_id.resolve()
    else:
        assert dbus_machine_id.read_text(encoding="utf-8").strip() == machine_id


def test_ensure_machine_id_keeps_existing_value(monkeypatch, tmp_path):
    existing_machine_id = "0123456789abcdef0123456789abcdef"
    etc_machine_id = tmp_path / "etc" / "machine-id"
    dbus_machine_id = tmp_path / "var" / "lib" / "dbus" / "machine-id"
    etc_machine_id.parent.mkdir(parents=True, exist_ok=True)
    etc_machine_id.write_text(f"{existing_machine_id}\n", encoding="utf-8")

    monkeypatch.setattr(runtime_bootstrap, "ETC_MACHINE_ID_PATH", str(etc_machine_id))
    monkeypatch.setattr(runtime_bootstrap, "DBUS_MACHINE_ID_PATH", str(dbus_machine_id))

    runtime_bootstrap.ensure_machine_id(logging.getLogger("test-machine-id-existing"))

    assert etc_machine_id.read_text(encoding="utf-8").strip() == existing_machine_id
    assert dbus_machine_id.exists()


def test_ensure_machine_id_write_error_is_non_fatal(monkeypatch, tmp_path, caplog):
    etc_machine_id = tmp_path / "etc" / "machine-id"
    dbus_machine_id = tmp_path / "var" / "lib" / "dbus" / "machine-id"

    monkeypatch.setattr(runtime_bootstrap, "ETC_MACHINE_ID_PATH", str(etc_machine_id))
    monkeypatch.setattr(runtime_bootstrap, "DBUS_MACHINE_ID_PATH", str(dbus_machine_id))

    real_write_text = runtime_bootstrap.Path.write_text

    def fake_write_text(path_obj, *args, **kwargs):
        if path_obj == etc_machine_id:
            raise OSError("permission denied")
        return real_write_text(path_obj, *args, **kwargs)

    monkeypatch.setattr(runtime_bootstrap.Path, "write_text", fake_write_text)
    caplog.set_level(logging.WARNING)

    runtime_bootstrap.ensure_machine_id(logging.getLogger("test-machine-id-error"))

    assert "Failed to initialize /etc/machine-id" in caplog.text


def _proton_env(monkeypatch):
    monkeypatch.delenv("PROTON_VERSION", raising=False)
    monkeypatch.delenv(runtime_proton.PROTON_VERSION_SOURCE_ENV, raising=False)
    monkeypatch.delenv("PROTON_SKIP_PREFLIGHT", raising=False)


def _write_proton_script(tmp_path, proton_dir_name):
    proton_dir = tmp_path / proton_dir_name
    proton_dir.mkdir(parents=True, exist_ok=True)
    script = proton_dir / "proton"
    script.write_text("stub", encoding="utf-8")
    return script


def test_asset_bases_prefer_plain_then_architecture(monkeypatch):
    monkeypatch.setattr(runtime_proton.platform, "machine", lambda: "x86_64")
    assert runtime_proton._asset_bases("11-5") == ["GE-Proton11-5", "GE-Proton11-5-x86_64"]

    monkeypatch.setattr(runtime_proton.platform, "machine", lambda: "aarch64")
    assert runtime_proton._asset_bases("11-5") == ["GE-Proton11-5", "GE-Proton11-5-aarch64"]


def test_find_release_archive_falls_back_to_architecture_asset(monkeypatch):
    monkeypatch.setattr(runtime_proton.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        runtime_proton,
        "_asset_exists",
        lambda url: "GE-Proton11-5-x86_64" in url,
    )

    release = runtime_proton.find_release_archive("11-5")

    assert release is not None
    assert release.asset_base == "GE-Proton11-5-x86_64"
    assert release.archive_url.endswith("/GE-Proton11-5-x86_64.tar.gz")
    assert release.checksum_url.endswith("/GE-Proton11-5-x86_64.sha512sum")


def test_find_release_archive_without_matching_assets(monkeypatch):
    monkeypatch.setattr(runtime_proton, "_asset_exists", lambda _url: False)
    assert runtime_proton.find_release_archive("11-5") is None


def test_canonicalize_install_dir_renames_architecture_directory(tmp_path):
    (tmp_path / "GE-Proton11-5-x86_64").mkdir()
    release = runtime_proton.ReleaseArchive(
        version="11-5",
        asset_base="GE-Proton11-5-x86_64",
        archive_url="https://example.invalid/a.tar.gz",
        checksum_url="https://example.invalid/a.sha512sum",
    )

    runtime_proton._canonicalize_install_dir(tmp_path / "GE-Proton11-5", release)

    assert (tmp_path / "GE-Proton11-5").is_dir()
    assert not (tmp_path / "GE-Proton11-5-x86_64").exists()


def test_canonicalize_install_dir_rejects_unexpected_layout(tmp_path):
    release = runtime_proton.ReleaseArchive(
        version="11-5",
        asset_base="GE-Proton11-5-x86_64",
        archive_url="https://example.invalid/a.tar.gz",
        checksum_url="https://example.invalid/a.sha512sum",
    )

    with pytest.raises(RuntimeError, match="did not contain the expected"):
        runtime_proton._canonicalize_install_dir(tmp_path / "GE-Proton11-5", release)


@pytest.mark.parametrize("checksum_content", [None, "wrong checksum\n"])
def test_proton_install_rejects_unverified_archive_before_extraction(
    monkeypatch, tmp_path, checksum_content
):
    release = runtime_proton.ReleaseArchive(
        version="11-5",
        asset_base="GE-Proton11-5",
        archive_url="https://example.invalid/GE-Proton11-5.tar.gz",
        checksum_url="https://example.invalid/GE-Proton11-5.sha512sum",
    )
    monkeypatch.setattr(runtime_proton, "STEAM_COMPAT_DIR", str(tmp_path))
    monkeypatch.setattr(runtime_proton, "find_release_archive", lambda _: release)

    def fake_download(url, destination):
        if url == release.checksum_url and checksum_content is None:
            raise runtime_proton.urllib.error.URLError("unavailable")
        destination.write_bytes(
            b"unverified archive" if url == release.archive_url else checksum_content.encode()
        )

    extract = Mock()
    monkeypatch.setattr(runtime_proton, "_download_file", fake_download)
    monkeypatch.setattr(runtime_proton, "safe_extract_archive", extract)

    with pytest.raises(RuntimeError, match="Proton checksum verification failed"):
        runtime_proton.install_proton_if_needed(
            "11-5", logging.getLogger("test-proton-checksum"), RuntimeSettings.from_env({})
        )

    extract.assert_not_called()
    assert not (tmp_path / "GE-Proton11-5").exists()


def test_find_missing_proton_library_detects_missing_shared_object(monkeypatch, tmp_path):
    _proton_env(monkeypatch)
    _write_proton_script(tmp_path, "GE-Proton11-3")
    monkeypatch.setattr(runtime_proton, "STEAM_COMPAT_DIR", str(tmp_path))
    captured = {}

    def fake_run(command, **kwargs):
        captured["env"] = kwargs["env"]
        return Mock(
            stdout="",
            stderr="OSError: libvulkan.so.1: cannot open shared object file: No such file",
        )

    monkeypatch.setenv("STEAM_COMPAT_DATA_PATH", "/should/be/dropped")
    monkeypatch.setattr(runtime_proton.subprocess, "run", fake_run)

    missing = runtime_proton.find_missing_proton_library(
        "GE-Proton11-3", logging.getLogger("test-preflight")
    )

    assert missing == "libvulkan.so.1"
    assert "STEAM_COMPAT_DATA_PATH" not in captured["env"]


def test_find_missing_proton_library_ignores_unrelated_failure(monkeypatch, tmp_path):
    _proton_env(monkeypatch)
    _write_proton_script(tmp_path, "GE-Proton11-3")
    monkeypatch.setattr(runtime_proton, "STEAM_COMPAT_DIR", str(tmp_path))
    monkeypatch.setattr(
        runtime_proton.subprocess,
        "run",
        lambda command, **kwargs: Mock(stdout="Proton: No compat data path?", stderr=""),
    )

    assert (
        runtime_proton.find_missing_proton_library(
            "GE-Proton11-3", logging.getLogger("test-preflight")
        )
        is None
    )


def test_find_missing_proton_library_fails_open(monkeypatch, tmp_path):
    _proton_env(monkeypatch)
    _write_proton_script(tmp_path, "GE-Proton11-3")
    monkeypatch.setattr(runtime_proton, "STEAM_COMPAT_DIR", str(tmp_path))

    def explode(command, **kwargs):
        raise OSError("cannot spawn")

    monkeypatch.setattr(runtime_proton.subprocess, "run", explode)

    assert (
        runtime_proton.find_missing_proton_library(
            "GE-Proton11-3", logging.getLogger("test-preflight")
        )
        is None
    )


def test_find_missing_proton_library_can_be_skipped(monkeypatch, tmp_path):
    _proton_env(monkeypatch)
    _write_proton_script(tmp_path, "GE-Proton11-3")
    monkeypatch.setattr(runtime_proton, "STEAM_COMPAT_DIR", str(tmp_path))
    monkeypatch.setenv("PROTON_SKIP_PREFLIGHT", "1")

    def explode(command, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("preflight should be skipped")

    monkeypatch.setattr(runtime_proton.subprocess, "run", explode)

    assert (
        runtime_proton.find_missing_proton_library(
            "GE-Proton11-3", logging.getLogger("test-preflight")
        )
        is None
    )


def test_prepare_proton_returns_verified_install(monkeypatch):
    _proton_env(monkeypatch)
    monkeypatch.setattr(runtime_proton, "resolve_proton_version", lambda _logger: "11-3")
    monkeypatch.setattr(
        runtime_proton,
        "install_proton_if_needed",
        lambda version, _logger, _settings=None: f"GE-Proton{version}",
    )
    monkeypatch.setattr(runtime_proton, "find_missing_proton_library", lambda _name, _logger: None)

    assert runtime_proton.prepare_proton(logging.getLogger("test-prepare")) == "GE-Proton11-3"


def test_prepare_proton_falls_back_when_detected_build_is_unsupported(monkeypatch, caplog):
    _proton_env(monkeypatch)
    installed = []
    monkeypatch.setattr(runtime_proton, "resolve_proton_version", lambda _logger: "11-3")

    def fake_install(version, _logger, _settings=None):
        installed.append(version)
        return f"GE-Proton{version}"

    def fake_missing(proton_dir_name, _logger):
        return "libvulkan.so.1" if proton_dir_name == "GE-Proton11-3" else None

    monkeypatch.setattr(runtime_proton, "install_proton_if_needed", fake_install)
    monkeypatch.setattr(runtime_proton, "find_missing_proton_library", fake_missing)
    caplog.set_level(logging.WARNING)

    proton_dir_name = runtime_proton.prepare_proton(logging.getLogger("test-prepare"))

    assert proton_dir_name == f"GE-Proton{runtime_proton.FALLBACK_PROTON_VERSION}"
    assert installed == ["11-3", runtime_proton.FALLBACK_PROTON_VERSION]
    assert os.environ["PROTON_VERSION"] == runtime_proton.FALLBACK_PROTON_VERSION
    assert "libvulkan.so.1" in caplog.text


def test_prepare_proton_does_not_swap_pinned_version(monkeypatch):
    _proton_env(monkeypatch)
    monkeypatch.setenv("PROTON_VERSION", "11-3")
    monkeypatch.setattr(runtime_proton, "resolve_proton_version", lambda _logger: "11-3")
    monkeypatch.setattr(
        runtime_proton,
        "install_proton_if_needed",
        lambda version, _logger, _settings=None: f"GE-Proton{version}",
    )
    monkeypatch.setattr(
        runtime_proton, "find_missing_proton_library", lambda _name, _logger: "libvulkan.so.1"
    )

    with pytest.raises(RuntimeError, match="Pinned GE-Proton11-3"):
        runtime_proton.prepare_proton(logging.getLogger("test-prepare"))


def test_resolve_proton_version_reuses_auto_detected_value(monkeypatch):
    _proton_env(monkeypatch)
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return {"tag_name": "GE-Proton11-3"}

    monkeypatch.setattr(runtime_proton, "_fetch_json", fake_fetch)
    monkeypatch.setattr(runtime_proton, "_check_release_assets", lambda _version: True)
    logger = logging.getLogger("test-resolve")

    assert runtime_proton.resolve_proton_version(logger) == "11-3"
    assert os.environ[runtime_proton.PROTON_VERSION_SOURCE_ENV] == "auto"

    assert runtime_proton.resolve_proton_version(logger) == "11-3"
    assert len(calls) == 1


def test_resolve_proton_version_marks_pinned_value(monkeypatch):
    _proton_env(monkeypatch)
    monkeypatch.setenv("PROTON_VERSION", "10-34")

    version = runtime_proton.resolve_proton_version(logging.getLogger("test-resolve"))

    assert version == "10-34"
    assert os.environ[runtime_proton.PROTON_VERSION_SOURCE_ENV] == "pinned"


def test_missing_native_libraries_reports_unloadable_entries(monkeypatch, caplog):
    library = runtime_native_libs.NativeLibrary(
        soname="libnot-there.so.1",
        package="libnot-there1",
        reason="test only",
    )
    monkeypatch.setattr(runtime_native_libs, "REQUIRED_NATIVE_LIBRARIES", (library,))
    caplog.set_level(logging.WARNING)

    missing = runtime_native_libs.warn_about_missing_native_libraries(
        logging.getLogger("test-native-libs")
    )

    assert missing == [library]
    assert "libnot-there1" in caplog.text


def test_missing_native_libraries_accepts_loadable_entries(monkeypatch):
    monkeypatch.setattr(runtime_native_libs, "_is_loadable", lambda _soname: True)
    assert runtime_native_libs.missing_native_libraries() == []


def test_runtime_settings_validate_mode_defaults_to_first(monkeypatch):
    monkeypatch.delenv("ASA_VALIDATE", raising=False)

    assert RuntimeSettings.from_env().validate_mode_or_default() == "first"


def test_runtime_settings_validate_mode_falls_back_on_garbage():
    settings = RuntimeSettings.from_env({"ASA_VALIDATE": "Always"})
    assert settings.validate_mode_or_default() == "always"

    settings = RuntimeSettings.from_env({"ASA_VALIDATE": "sometimes"})
    assert settings.validate_mode_or_default() == "first"


def _steamcmd_run_recorder(monkeypatch, tmp_path, installed):
    """Point steamcmd at a temp install and capture the command it would run."""
    binary_dir = tmp_path / "ShooterGame" / "Binaries" / "Win64"
    binary_dir.mkdir(parents=True, exist_ok=True)
    if installed:
        (binary_dir / "ArkAscendedServer.exe").write_text("stub", encoding="utf-8")

    recorded = {}

    def fake_run(command, **kwargs):
        recorded["command"] = command
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(runtime_steamcmd, "ASA_BINARY_DIR", str(binary_dir))
    monkeypatch.setattr(runtime_steamcmd.subprocess, "run", fake_run)
    return recorded


def test_update_server_files_validates_on_first_install(monkeypatch, tmp_path):
    recorded = _steamcmd_run_recorder(monkeypatch, tmp_path, installed=False)

    runtime_steamcmd.update_server_files(
        logging.getLogger("test-validate-first"), RuntimeSettings.from_env({})
    )

    assert "validate" in recorded["command"]


def test_update_server_files_skips_validation_once_installed(monkeypatch, tmp_path):
    recorded = _steamcmd_run_recorder(monkeypatch, tmp_path, installed=True)

    runtime_steamcmd.update_server_files(
        logging.getLogger("test-validate-installed"), RuntimeSettings.from_env({})
    )

    assert "validate" not in recorded["command"]
    # The update itself still runs, so new builds are still picked up.
    assert "+app_update" in recorded["command"]
    assert recorded["command"][-1] == "+quit"


def test_update_server_files_honours_always_and_never(monkeypatch, tmp_path):
    recorded = _steamcmd_run_recorder(monkeypatch, tmp_path, installed=True)
    runtime_steamcmd.update_server_files(
        logging.getLogger("test-validate-always"),
        RuntimeSettings.from_env({"ASA_VALIDATE": "always"}),
    )
    assert "validate" in recorded["command"]

    recorded = _steamcmd_run_recorder(monkeypatch, tmp_path, installed=False)
    runtime_steamcmd.update_server_files(
        logging.getLogger("test-validate-never"),
        RuntimeSettings.from_env({"ASA_VALIDATE": "never"}),
    )
    assert "validate" not in recorded["command"]


def _preflight_probe_counter(monkeypatch, tmp_path, stderr):
    """Install a fake GE-Proton tree and count preflight subprocess launches."""
    compat_dir = tmp_path / "compatibilitytools.d"
    (compat_dir / "GE-Proton9-9").mkdir(parents=True, exist_ok=True)
    (compat_dir / "GE-Proton9-9" / "proton").write_text("stub", encoding="utf-8")

    calls = {"count": 0}

    def fake_run(_command, **_kwargs):
        calls["count"] += 1
        return subprocess.CompletedProcess([], 0, stdout="", stderr=stderr)

    monkeypatch.setattr(runtime_proton, "STEAM_COMPAT_DIR", str(compat_dir))
    monkeypatch.setattr(runtime_proton.subprocess, "run", fake_run)
    monkeypatch.delenv("PROTON_SKIP_PREFLIGHT", raising=False)
    return calls


def test_preflight_result_is_cached_per_image_version(monkeypatch, tmp_path):
    calls = _preflight_probe_counter(monkeypatch, tmp_path, stderr="")
    monkeypatch.setenv("ASA_IMAGE_VERSION", "2.1.0")
    logger = logging.getLogger("test-preflight-cache")

    assert runtime_proton.find_missing_proton_library("GE-Proton9-9", logger) is None
    assert runtime_proton.find_missing_proton_library("GE-Proton9-9", logger) is None
    assert calls["count"] == 1


def test_preflight_cache_remembers_a_missing_library(monkeypatch, tmp_path):
    calls = _preflight_probe_counter(
        monkeypatch, tmp_path, stderr="libvulkan.so.1: cannot open shared object file"
    )
    monkeypatch.setenv("ASA_IMAGE_VERSION", "2.1.0")
    logger = logging.getLogger("test-preflight-cache-missing")

    assert runtime_proton.find_missing_proton_library("GE-Proton9-9", logger) == "libvulkan.so.1"
    assert runtime_proton.find_missing_proton_library("GE-Proton9-9", logger) == "libvulkan.so.1"
    assert calls["count"] == 1


def test_preflight_cache_is_invalidated_by_a_new_image(monkeypatch, tmp_path):
    calls = _preflight_probe_counter(monkeypatch, tmp_path, stderr="")
    logger = logging.getLogger("test-preflight-cache-invalidation")

    monkeypatch.setenv("ASA_IMAGE_VERSION", "2.1.0")
    runtime_proton.find_missing_proton_library("GE-Proton9-9", logger)
    monkeypatch.setenv("ASA_IMAGE_VERSION", "2.2.0")
    runtime_proton.find_missing_proton_library("GE-Proton9-9", logger)

    assert calls["count"] == 2


def test_preflight_is_never_cached_for_untagged_builds(monkeypatch, tmp_path):
    calls = _preflight_probe_counter(monkeypatch, tmp_path, stderr="")
    monkeypatch.setenv("ASA_IMAGE_VERSION", "unknown")
    logger = logging.getLogger("test-preflight-cache-unknown")

    runtime_proton.find_missing_proton_library("GE-Proton9-9", logger)
    runtime_proton.find_missing_proton_library("GE-Proton9-9", logger)

    assert calls["count"] == 2


def test_log_sync_mode_prefers_fsync_on_a_modern_kernel(monkeypatch):
    monkeypatch.delenv("PROTON_NO_FSYNC", raising=False)
    monkeypatch.setattr(runtime_wine_sync.platform, "release", lambda: "6.8.0-generic")

    assert runtime_wine_sync.log_sync_mode(logging.getLogger("test-fsync"), 1024) == "fsync"


def test_log_sync_mode_falls_back_to_esync_when_descriptors_allow(monkeypatch):
    monkeypatch.setenv("PROTON_NO_FSYNC", "1")
    monkeypatch.delenv("PROTON_NO_ESYNC", raising=False)
    monkeypatch.setattr(runtime_wine_sync.platform, "release", lambda: "5.10.0-generic")

    mode = runtime_wine_sync.log_sync_mode(logging.getLogger("test-esync"), 1048576)
    assert mode == "esync"


def test_log_sync_mode_warns_when_only_the_slow_path_is_left(monkeypatch, caplog):
    monkeypatch.delenv("PROTON_NO_FSYNC", raising=False)
    monkeypatch.delenv("PROTON_NO_ESYNC", raising=False)
    monkeypatch.setattr(runtime_wine_sync.platform, "release", lambda: "5.10.0-generic")

    with caplog.at_level(logging.WARNING):
        mode = runtime_wine_sync.log_sync_mode(logging.getLogger("test-slow-sync"), 1024)

    assert mode == "server"
    assert "slow server path" in caplog.text
