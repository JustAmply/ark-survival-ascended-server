"""Regression coverage for the isolated ARM64 execution adapter."""

import logging
import os
import shlex
import subprocess
import time
from dataclasses import replace
from unittest.mock import MagicMock, Mock

import pytest

from server_runtime import launch_env, proton, steamcmd, supervisor, translation
from server_runtime.constants import RuntimeSettings


LOGGER = logging.getLogger("test-translation")


def context():
    return translation.ExecutionContext(
        architecture="arm64",
        translator_mode="fex",
        runner_prefix=("/usr/bin/FEXBash", "-c"),
        wraps_with_shell=True,
        probe_timeout=20,
    )


def test_execution_context_uses_explicit_settings(monkeypatch):
    monkeypatch.setenv("ASA_TRANSLATOR_MODE", "fex")
    monkeypatch.setenv("ASA_PROTON_PROFILE", "safe")
    monkeypatch.setattr(translation.platform, "machine", lambda: "aarch64")
    settings = RuntimeSettings.from_env({"ASA_TRANSLATOR_MODE": "none"})
    result = translation.resolve_execution_context(LOGGER, settings)
    assert result.translator_mode == "none"


@pytest.mark.parametrize("runner", ["FEXBash", "FEX", "FEXInterpreter"])
def test_resolved_runner_uses_guest_shell(monkeypatch, runner):
    monkeypatch.setattr(translation.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(translation.shutil, "which", lambda name: f"/usr/bin/{name}" if name == runner else None)
    result = translation.resolve_execution_context(LOGGER, RuntimeSettings.from_env({}))
    assert result.architecture == "arm64"
    assert result.translator_mode == "fex"
    assert result.probe_timeout == 20
    expected = (f"/usr/bin/{runner}", "-c") if runner == "FEXBash" else (f"/usr/bin/{runner}", "/bin/sh", "-c")
    assert result.runner_prefix == expected
    assert result.wraps_with_shell


def test_wrap_command_preserves_argv_and_executes_without_extra_shell():
    argv = ["/path with space/tool", "", "Map?SessionName=hello world", "$(touch /tmp/unwanted)"]
    result = translation.wrap_command(context(), argv)
    assert result[:2] == ["/usr/bin/FEXBash", "-c"]
    assert shlex.split(result[2]) == ["exec", *argv]


@pytest.mark.parametrize("timeout", [0, -5])
def test_nonpositive_probe_timeout_uses_default(monkeypatch, timeout):
    monkeypatch.setattr(translation.platform, "machine", lambda: "x86_64")
    settings = replace(RuntimeSettings.from_env({}), translator_probe_timeout=timeout)
    assert translation.resolve_execution_context(LOGGER, settings).probe_timeout == 20


@pytest.mark.parametrize("mode,installed,validate", [("always", True, True), ("never", False, False), ("first", False, True), ("first", True, False)])
def test_translated_update_preserves_steamcmd_wrapper_and_validation(monkeypatch, tmp_path, mode, installed, validate):
    monkeypatch.setattr(steamcmd, "STEAMCMD_DIR", str(tmp_path))
    monkeypatch.setattr(steamcmd, "server_is_installed", lambda: installed)
    run = Mock()
    monkeypatch.setattr(steamcmd.subprocess, "run", run)
    settings = RuntimeSettings.from_env({"ASA_VALIDATE": mode})
    steamcmd.update_server_files(LOGGER, settings, execution_context=context())
    argv = shlex.split(run.call_args.args[0][-1])
    assert argv[:2] == ["exec", str(tmp_path / "steamcmd.sh")]
    assert ("validate" in argv) is validate
    assert argv[-1] == "+quit"
    assert run.call_args.kwargs == {"cwd": str(tmp_path), "check": True}


def test_translation_probe_uses_steamcmd_script(monkeypatch, tmp_path):
    (tmp_path / "steamcmd.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(steamcmd, "STEAMCMD_DIR", str(tmp_path))
    process = MagicMock(returncode=0)
    process.__enter__.return_value = process
    process.communicate.return_value = (None, "")
    run = Mock(return_value=process)
    monkeypatch.setattr(translation.subprocess, "Popen", run)
    execution_context = context()
    steamcmd.probe_steamcmd_translation(execution_context, LOGGER)
    run.assert_called_once()
    assert shlex.split(run.call_args.args[0][-1]) == ["exec", str(tmp_path / "steamcmd.sh"), "+quit"]


@pytest.mark.skipif(os.name != "posix", reason="Process groups require POSIX")
def test_probe_timeout_stops_wrapper_children(tmp_path):
    marker = tmp_path / "child-survived"
    started = tmp_path / "child-started"
    child = tmp_path / "child.sh"
    child.write_text(
        f"echo started > {shlex.quote(str(started))}; sleep 2; echo child > {shlex.quote(str(marker))}\n",
        encoding="utf-8",
    )
    wrapper = tmp_path / "wrapper.sh"
    wrapper.write_text(f"/bin/sh {shlex.quote(str(child))} & wait\n", encoding="utf-8")
    execution_context = replace(context(), runner_prefix=("/bin/sh", "-c"), probe_timeout=1)
    with pytest.raises(RuntimeError, match="timed out after 1s"):
        translation.run_probe_command(execution_context, ["/bin/sh", str(wrapper)], tmp_path, LOGGER, "fixture")
    assert started.is_file(), "The child must have started for this test to exercise cleanup"
    time.sleep(1.5)
    assert not marker.exists(), "The probe left a child running after its timeout"


def test_safe_profile_overrides_enabled_sync_without_mutating_base(monkeypatch):
    monkeypatch.setattr(launch_env, "_resolve_runtime_dir", lambda _: "/tmp/fixture-runtime")
    base = {"PROTON_NO_ESYNC": "0", "PROTON_NO_FSYNC": "0", "WINEDEBUG": "+warn"}
    environment = launch_env.LaunchEnvironment.from_process(
        RuntimeSettings.from_env({"ASA_PROTON_PROFILE": "safe"}), base
    )
    safe = environment.for_server("Map?listen")
    assert safe["PROTON_NO_ESYNC"] == "1"
    assert safe["PROTON_NO_FSYNC"] == "1"
    assert safe["WINEDEBUG"] == "+warn"
    assert safe["ASA_START_PARAMS"] == "Map?listen"
    assert base["PROTON_NO_ESYNC"] == "0"
    balanced = environment.for_server(proton_profile="balanced")
    assert balanced["PROTON_NO_ESYNC"] == "0"
    assert balanced["PROTON_NO_FSYNC"] == "0"
    assert environment.settings.proton_profile == "safe"


@pytest.mark.parametrize("configured, expected", [(" Safe ", "safe"), ("invalid", "balanced"), ("", "balanced")])
def test_server_environment_normalizes_configured_profile(monkeypatch, configured, expected):
    monkeypatch.setattr(launch_env, "_resolve_runtime_dir", lambda _: "/tmp/fixture-runtime")
    settings = RuntimeSettings.from_env({"ASA_PROTON_PROFILE": configured})
    environment = launch_env.LaunchEnvironment.from_process(settings, {}).for_server()
    assert environment.get("PROTON_NO_ESYNC") == ("1" if expected == "safe" else None)
    assert environment.get("PROTON_NO_FSYNC") == ("1" if expected == "safe" else None)


def test_supervisor_caches_only_successful_probe_across_preparation_failures(monkeypatch):
    execution_context = context()
    monkeypatch.setattr(supervisor, "resolve_execution_context", lambda *_: execution_context)
    owner = supervisor.ServerSupervisor(RuntimeSettings.from_env({}), LOGGER)
    probe = Mock(side_effect=[RuntimeError("probe failed"), None])
    update = Mock(side_effect=RuntimeError("update failed"))
    monkeypatch.setattr(supervisor, "probe_steamcmd_translation", probe)
    monkeypatch.setattr(supervisor, "update_server_files", update)

    with pytest.raises(RuntimeError, match="probe failed"):
        owner._launch_server_once()
    assert owner.translator_probe_complete is False
    for _ in range(2):
        with pytest.raises(RuntimeError, match="update failed"):
            owner._launch_server_once()
    assert probe.call_count == 2
    assert update.call_count == 2
    assert owner.translator_probe_complete is True
    assert owner.proton_profile == "balanced"
    assert owner.quick_crash_count == 0
    assert owner.execution_context == execution_context


@pytest.mark.parametrize("reset_reason", ["long run", "scheduled restart"])
def test_translated_supervisor_resets_early_crash_count(monkeypatch, reset_reason):
    monkeypatch.setattr(supervisor, "resolve_execution_context", lambda *_: context())
    owner = supervisor.ServerSupervisor(RuntimeSettings.from_env({}), LOGGER)
    attempts = []

    def launch():
        attempts.append(owner.proton_profile)
        owner.last_run_duration = 1
        if len(attempts) == 2:
            if reset_reason == "long run":
                owner.last_run_duration = 240
            else:
                owner.restart_requested = True
        if len(attempts) == 4:
            owner.supervisor_exit_requested = True
        return 2

    monkeypatch.setattr(owner, "_launch_server_once", launch)
    monkeypatch.setattr(owner, "_cleanup_after_run", lambda: None)
    monkeypatch.setattr(supervisor.time, "sleep", lambda _: None)
    assert owner.run() == 2
    assert attempts == ["balanced"] * 4
    assert owner.quick_crash_count == 1


def test_native_update_retains_os_error_contract(monkeypatch):
    native = replace(context(), architecture="amd64", translator_mode="none", runner_prefix=())
    monkeypatch.setattr(steamcmd.subprocess, "run", Mock(side_effect=OSError("native spawn failed")))
    with pytest.raises(OSError, match="native spawn failed"):
        steamcmd.update_server_files(LOGGER, RuntimeSettings.from_env({}), execution_context=native)


def test_translated_arm64_selects_x86_proton_assets(monkeypatch):
    monkeypatch.setattr(proton.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(proton, "_asset_exists", lambda url: "-x86_64." in url)
    result = proton.find_release_archive("11-5", context())
    assert result.asset_base == "GE-Proton11-5-x86_64"
    assert proton.find_release_archive("11-5") is None


def test_native_proton_assets_use_supplied_architecture(monkeypatch):
    monkeypatch.setattr(proton.platform, "machine", lambda: "aarch64")
    native = replace(context(), architecture="amd64", translator_mode="none", runner_prefix=())
    assert proton._asset_bases("11-5", native) == ["GE-Proton11-5", "GE-Proton11-5-x86_64"]


def test_translated_preflight_uses_guest_python_and_separate_cache(monkeypatch, tmp_path):
    tree = tmp_path / "GE-Proton11-5"
    tree.mkdir()
    (tree / "proton").write_text("# preflight fixture\n", encoding="utf-8")
    monkeypatch.setattr(proton, "STEAM_COMPAT_DIR", str(tmp_path))
    monkeypatch.setenv("STEAM_COMPAT_DATA_PATH", "/should/not/be/used")
    settings = RuntimeSettings.from_env({"ASA_IMAGE_VERSION": "test-image"})
    run = Mock(return_value=subprocess.CompletedProcess([], 1, stdout="", stderr="libvulkan.so.1: cannot open shared object file"))
    monkeypatch.setattr(proton.subprocess, "run", run)
    # A native success cannot bypass the check against the guest rootfs.
    proton._write_preflight_cache("GE-Proton11-5", "test-image", None)
    assert proton.find_missing_proton_library("GE-Proton11-5", LOGGER, settings, context()) == "libvulkan.so.1"
    assert shlex.split(run.call_args.args[0][-1]) == ["exec", "/usr/bin/python3", str(tree / "proton")]
    assert "STEAM_COMPAT_DATA_PATH" not in run.call_args.kwargs["env"]
    assert proton.find_missing_proton_library("GE-Proton11-5", LOGGER, settings, context()) == "libvulkan.so.1"
    run.assert_called_once()


def test_prepare_proton_passes_translator_to_resolution_install_and_preflight(monkeypatch):
    monkeypatch.setenv("PROTON_VERSION", "")
    execution_context = context()
    settings = RuntimeSettings.from_env({"PROTON_VERSION": "11-5"})
    selection = proton.ProtonSelection("11-5", proton.ORIGIN_PINNED)
    resolve = Mock(return_value=selection)
    install = Mock()
    preflight = Mock(return_value=None)
    monkeypatch.setattr(proton, "resolve_proton_version", resolve)
    monkeypatch.setattr(proton, "install_proton_if_needed", install)
    monkeypatch.setattr(proton, "find_missing_proton_library", preflight)
    assert proton.prepare_proton(LOGGER, settings, execution_context=execution_context) == selection
    resolve.assert_called_once_with(LOGGER, settings, None, execution_context=execution_context)
    install.assert_called_once_with("11-5", LOGGER, settings, execution_context=execution_context)
    preflight.assert_called_once_with("GE-Proton11-5", LOGGER, settings, execution_context=execution_context)


@pytest.mark.parametrize("profile", ["balanced", "safe"])
def test_native_supervisor_retries_short_runs_without_profile_escalation(monkeypatch, profile):
    from server_runtime import supervisor as runtime

    settings = replace(RuntimeSettings.from_env({}), translator_mode="none", proton_profile=profile)
    owner = runtime.ServerSupervisor(settings, LOGGER)
    attempts = []

    def launch():
        attempts.append(owner.proton_profile)
        owner.last_run_duration = 1
        if len(attempts) == 4:
            owner.supervisor_exit_requested = True
        return 2

    monkeypatch.setattr(owner, "_launch_server_once", launch)
    monkeypatch.setattr(owner, "_cleanup_after_run", lambda: None)
    monkeypatch.setattr(runtime.time, "sleep", lambda _: None)
    assert owner.run() == 2
    assert attempts == [profile] * 4


def test_safe_profile_sync_report_uses_child_environment(monkeypatch, caplog):
    from server_runtime import wine_sync

    monkeypatch.setenv("PROTON_NO_ESYNC", "0")
    monkeypatch.setenv("PROTON_NO_FSYNC", "0")
    monkeypatch.setattr(wine_sync, "kernel_version", lambda: (6, 8))
    monkeypatch.setattr(launch_env, "_resolve_runtime_dir", lambda _: "/tmp/fixture-runtime")
    env = launch_env.LaunchEnvironment.from_process(
        RuntimeSettings.from_env({"ASA_PROTON_PROFILE": "safe"}), {}
    ).for_server()
    with caplog.at_level(logging.WARNING):
        mode = wine_sync.log_sync_mode(LOGGER, wine_sync.ESYNC_RECOMMENDED_NOFILE, env)
    assert mode == "server"
    assert "slow server path" in caplog.text
    assert wine_sync.os.environ["PROTON_NO_ESYNC"] == "0"
    assert wine_sync.os.environ["PROTON_NO_FSYNC"] == "0"
