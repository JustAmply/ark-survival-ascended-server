from __future__ import annotations

import logging
import os
import signal
import tarfile
from unittest.mock import Mock

import pytest

from server_runtime import bootstrap as runtime_bootstrap
from server_runtime import logging_utils as runtime_logging
from server_runtime import params as runtime_params
from server_runtime import permissions as runtime_permissions
from server_runtime import proton as runtime_proton
from server_runtime import steamcmd as runtime_steamcmd
from server_runtime import translation as runtime_translation
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

def test_resolve_execution_context_auto_arm64_uses_fex(monkeypatch):
    monkeypatch.delenv("ASA_TRANSLATOR_MODE", raising=False)
    monkeypatch.delenv("ASA_TRANSLATOR_PROBE_TIMEOUT", raising=False)
    monkeypatch.delenv("ASA_PROTON_PROFILE", raising=False)
    monkeypatch.setattr(runtime_translation.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(
        runtime_translation.shutil,
        "which",
        lambda name: "/usr/bin/FEXBash" if name == "FEXBash" else None,
    )

    context = runtime_translation.resolve_execution_context(logging.getLogger("test-context"))

    assert context.architecture == "arm64"
    assert context.translator_mode == "fex"
    assert context.runner_prefix == ("/usr/bin/FEXBash", "-c")
    assert context.wraps_with_shell is True
    assert context.probe_timeout == 20
    assert context.proton_profile == "balanced"


def test_wrap_command_uses_shell_runner():
    context = runtime_translation.ExecutionContext(
        architecture="arm64",
        translator_mode="fex",
        runner_prefix=("/usr/bin/FEXBash", "-c"),
        wraps_with_shell=True,
        probe_timeout=20,
        proton_profile="balanced",
    )

    wrapped = runtime_translation.wrap_command(context, ["/path/to/tool", "arg one", "--flag"])

    assert wrapped[:2] == ["/usr/bin/FEXBash", "-c"]
    assert "/path/to/tool" in wrapped[2]
    assert "arg one" in wrapped[2]


def test_run_probe_command_sets_probe_complete(monkeypatch):
    context = runtime_translation.ExecutionContext(
        architecture="arm64",
        translator_mode="fex",
        runner_prefix=("/usr/bin/FEXInterpreter",),
        wraps_with_shell=False,
        probe_timeout=20,
        proton_profile="balanced",
    )

    result = Mock(returncode=0, stderr="")
    monkeypatch.setattr(runtime_translation.subprocess, "run", lambda *args, **kwargs: result)

    runtime_translation.run_probe_command(
        context,
        ["/home/gameserver/steamcmd/linux32/steamcmd", "+quit"],
        "/home/gameserver/steamcmd",
        logging.getLogger("test-probe"),
        "SteamCMD",
    )

    assert context.translator_probe_complete is True


def test_run_probe_command_raises_on_nonzero(monkeypatch):
    context = runtime_translation.ExecutionContext(
        architecture="arm64",
        translator_mode="fex",
        runner_prefix=("/usr/bin/FEXInterpreter",),
        wraps_with_shell=False,
        probe_timeout=20,
        proton_profile="balanced",
    )

    result = Mock(returncode=1, stderr="failed")
    monkeypatch.setattr(runtime_translation.subprocess, "run", lambda *args, **kwargs: result)

    with pytest.raises(RuntimeError, match="translation probe failed"):
        runtime_translation.run_probe_command(
            context,
            ["/home/gameserver/steamcmd/linux32/steamcmd", "+quit"],
            "/home/gameserver/steamcmd",
            logging.getLogger("test-probe"),
            "SteamCMD",
        )


def test_update_server_files_wraps_command_for_translator(monkeypatch, tmp_path):
    steamcmd_dir = tmp_path / "steamcmd"
    steamcmd_bin = steamcmd_dir / "linux32" / "steamcmd"
    steamcmd_bin.parent.mkdir(parents=True, exist_ok=True)
    steamcmd_bin.write_text("", encoding="utf-8")

    monkeypatch.setattr(runtime_steamcmd, "STEAMCMD_DIR", str(steamcmd_dir))
    monkeypatch.setattr(runtime_steamcmd, "SERVER_FILES_DIR", str(tmp_path / "server"))

    context = runtime_translation.ExecutionContext(
        architecture="arm64",
        translator_mode="fex",
        runner_prefix=("/usr/bin/FEXInterpreter",),
        wraps_with_shell=False,
        probe_timeout=20,
        proton_profile="balanced",
    )

    calls = {}

    def fake_run(command, cwd=None, check=False):
        calls["command"] = command
        calls["cwd"] = cwd
        calls["check"] = check

    monkeypatch.setattr(runtime_steamcmd.subprocess, "run", fake_run)

    runtime_steamcmd.update_server_files(logging.getLogger("test-steamcmd"), context)

    assert calls["command"][0] == "/usr/bin/FEXInterpreter"
    assert str(steamcmd_bin) in calls["command"]
    assert calls["cwd"] == str(steamcmd_dir)
    assert calls["check"] is True


def test_build_launch_command_wraps_proton_for_translator(monkeypatch, tmp_path):
    proton_root = tmp_path / "compat" / "GE-ProtonX"
    proton_root.mkdir(parents=True, exist_ok=True)
    proton_path = proton_root / "proton"
    proton_path.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(runtime_proton, "STEAM_COMPAT_DIR", str(tmp_path / "compat"))
    monkeypatch.setattr(runtime_proton.os, "access", lambda path, mode: True)

    context = runtime_translation.ExecutionContext(
        architecture="arm64",
        translator_mode="fex",
        runner_prefix=("/usr/bin/FEXBash", "-c"),
        wraps_with_shell=True,
        probe_timeout=20,
        proton_profile="balanced",
    )

    command = runtime_proton.build_launch_command(
        "GE-ProtonX",
        "ArkAscendedServer.exe",
        "Map?listen -nosteam",
        context,
    )

    assert command[:2] == ["/usr/bin/FEXBash", "-c"]
    assert str(proton_path) in command[2]
    assert "run ArkAscendedServer.exe" in command[2]


def test_supervisor_switches_to_safe_profile_after_two_early_crashes(monkeypatch):
    logger = logging.getLogger("test-safe-switch")
    settings = RuntimeSettings.from_env()
    context = runtime_translation.ExecutionContext(
        architecture="arm64",
        translator_mode="fex",
        runner_prefix=("/usr/bin/FEXInterpreter",),
        wraps_with_shell=False,
        probe_timeout=20,
        proton_profile="balanced",
    )

    monkeypatch.setattr("server_runtime.supervisor.resolve_execution_context", lambda _logger: context)
    supervisor = ServerSupervisor(settings, logger)

    runs = {"count": 0}

    def fake_launch():
        runs["count"] += 1
        supervisor.last_run_duration = 30
        if runs["count"] >= 3:
            supervisor.supervisor_exit_requested = True
        return 1

    monkeypatch.setattr(supervisor, "_launch_server_once", fake_launch)
    monkeypatch.setattr("server_runtime.supervisor.time.sleep", lambda _seconds: None)

    code = supervisor.run()

    assert code == 1
    assert runs["count"] == 3
    assert supervisor.execution_context.proton_profile == "safe"
    assert supervisor.safe_profile_retry_used is True


def test_supervisor_fails_fast_after_early_crash_in_safe_profile(monkeypatch):
    logger = logging.getLogger("test-safe-failfast")
    settings = RuntimeSettings.from_env()
    context = runtime_translation.ExecutionContext(
        architecture="arm64",
        translator_mode="fex",
        runner_prefix=("/usr/bin/FEXInterpreter",),
        wraps_with_shell=False,
        probe_timeout=20,
        proton_profile="safe",
    )

    monkeypatch.setattr("server_runtime.supervisor.resolve_execution_context", lambda _logger: context)
    supervisor = ServerSupervisor(settings, logger)

    def fake_launch():
        supervisor.last_run_duration = 25
        return 1

    monkeypatch.setattr(supervisor, "_launch_server_once", fake_launch)
    monkeypatch.setattr("server_runtime.supervisor.time.sleep", lambda _seconds: None)

    code = supervisor.run()

    assert code == 1


def test_supervisor_startup_exceptions_escalate_to_safe_failfast(monkeypatch):
    logger = logging.getLogger("test-safe-failfast-exception")
    settings = RuntimeSettings.from_env()
    context = runtime_translation.ExecutionContext(
        architecture="arm64",
        translator_mode="fex",
        runner_prefix=("/usr/bin/FEXInterpreter",),
        wraps_with_shell=False,
        probe_timeout=20,
        proton_profile="balanced",
    )

    monkeypatch.setattr("server_runtime.supervisor.resolve_execution_context", lambda _logger: context)
    supervisor = ServerSupervisor(settings, logger)

    runs = {"count": 0}

    def fake_launch():
        runs["count"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(supervisor, "_launch_server_once", fake_launch)
    monkeypatch.setattr("server_runtime.supervisor.time.sleep", lambda _seconds: None)

    code = supervisor.run()

    assert code == 1
    assert runs["count"] == 3
    assert supervisor.execution_context.proton_profile == "safe"
    assert supervisor.safe_profile_retry_used is True
