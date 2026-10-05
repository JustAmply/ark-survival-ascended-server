"""Regression checks for prefix-scoped cleanup of translated Wine sessions."""

import logging
from pathlib import Path
import shlex
import subprocess
from unittest.mock import Mock

import pytest

from server_runtime import proton
from server_runtime.translation import ExecutionContext


LOGGER = logging.getLogger("proton-cleanup")
CONTEXT = ExecutionContext(
    architecture="arm64", translator_mode="fex",
    runner_prefix=("/usr/bin/FEXBash", "-c"), wraps_with_shell=True,
    probe_timeout=20,
)


def test_cleanup_stops_and_waits_for_the_launched_prefix_without_mutating_environment(monkeypatch):
    monkeypatch.setattr(proton, "STEAM_COMPAT_DIR", "/fixture/compat")
    run = Mock()
    monkeypatch.setattr(proton.subprocess, "run", run)
    environment = {
        "STEAM_COMPAT_DATA_PATH": "/fixture/data with spaces",
        "WINEPREFIX": "/unrelated/prefix",
        "PROTON_NO_FSYNC": "1",
    }
    original = dict(environment)

    proton.stop_proton_session("GE-Proton10-34", CONTEXT, environment, LOGGER)

    assert run.call_count == 2
    for call, operation in zip(run.call_args_list, ("-k", "-w")):
        command = call.args[0]
        assert command[:2] == ["/usr/bin/FEXBash", "-c"]
        assert shlex.split(command[2]) == [
            "exec", str(Path("/fixture/compat") / "GE-Proton10-34/files/bin/wineserver"), operation
        ]
        assert call.kwargs["env"] == {
            **environment, "WINEPREFIX": str(Path("/fixture/data with spaces") / "pfx")
        }
        assert call.kwargs["check"] is True
        assert call.kwargs["capture_output"] is True
        assert call.kwargs["timeout"] == proton.PROTON_SHUTDOWN_TIMEOUT
    assert environment == original


@pytest.mark.parametrize("failed_operation", ["-k", "-w"])
def test_cleanup_reports_failure_and_does_not_continue(monkeypatch, failed_operation):
    error = subprocess.CalledProcessError(7, ["wineserver", failed_operation], stderr="fixture failure")
    results = [error] if failed_operation == "-k" else [None, error]
    run = Mock(side_effect=results)
    monkeypatch.setattr(proton.subprocess, "run", run)

    with pytest.raises(RuntimeError, match=f"wineserver {failed_operation} with exit code 7: fixture failure") as failure:
        proton.stop_proton_session("GE-Proton10-34", CONTEXT, {"STEAM_COMPAT_DATA_PATH": "/fixture/data"}, LOGGER)
    assert failure.value.__cause__ is error
    assert run.call_count == len(results)


def test_cleanup_wait_is_bounded_and_timeout_is_not_swallowed(monkeypatch):
    error = subprocess.TimeoutExpired(["wineserver", "-w"], proton.PROTON_SHUTDOWN_TIMEOUT)
    run = Mock(side_effect=[None, error])
    monkeypatch.setattr(proton.subprocess, "run", run)

    with pytest.raises(RuntimeError, match="timed out after 30s during wineserver -w") as failure:
        proton.stop_proton_session("GE-Proton10-34", CONTEXT, {"STEAM_COMPAT_DATA_PATH": "/fixture/data"}, LOGGER)
    assert failure.value.__cause__ is error
    assert run.call_count == 2


def test_cleanup_reports_missing_translator_without_continuing(monkeypatch):
    error = FileNotFoundError("missing FEX runner")
    run = Mock(side_effect=error)
    monkeypatch.setattr(proton.subprocess, "run", run)

    with pytest.raises(RuntimeError, match="translator mode 'fex': missing FEX runner") as failure:
        proton.stop_proton_session("GE-Proton10-34", CONTEXT, {"STEAM_COMPAT_DATA_PATH": "/fixture/data"}, LOGGER)
    assert failure.value.__cause__ is error
    assert run.call_count == 1
