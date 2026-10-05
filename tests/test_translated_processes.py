"""Real-process regression checks for the translated supervisor lifecycle."""

import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from dataclasses import replace

import pytest

from server_runtime.constants import RuntimeSettings
from server_runtime.supervisor import ServerSupervisor


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Translated images use Linux process groups")


def test_translated_stop_waits_for_graceful_child_after_leader_exit(tmp_path):
    ready = tmp_path / "ready"
    stopped = tmp_path / "stopped"
    child = tmp_path / "child.py"
    child.write_text(
        "import pathlib, signal, sys, time\n"
        "def stop(sig, frame):\n"
        "    time.sleep(1.2)\n"
        f"    pathlib.Path({str(stopped)!r}).write_text('saved')\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, stop)\n"
        f"pathlib.Path({str(ready)!r}).touch()\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    owner = ServerSupervisor(RuntimeSettings.from_env({"ASA_TRANSLATOR_MODE": "none"}), logging.getLogger("graceful-test"))
    owner.execution_context = replace(owner.execution_context, translator_mode="fex")
    leader = subprocess.Popen(
        [sys.executable, "-c", "import subprocess, sys, time; subprocess.Popen([sys.executable, sys.argv[1]]); time.sleep(60)", str(child)],
        start_new_session=True,
    )
    try:
        wait_for_file(ready, leader)
        owner._stop_server_process(leader)
        assert stopped.read_text() == "saved", "Cleanup interrupted the child's graceful shutdown"
        leader.wait(timeout=5)
    finally:
        try:
            os.killpg(leader.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        leader.wait(timeout=5)


def wait_for_file(path, process):
    deadline = time.monotonic() + 5
    while not path.exists():
        assert process.poll() is None, "The fixture exited before its child started"
        assert time.monotonic() < deadline, "The fixture child did not start"
        time.sleep(0.02)


def is_running(pid):
    try:
        state = (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[0]
    except FileNotFoundError:
        return False
    return state != "Z"


@pytest.mark.parametrize("leader_exits_first", [False, True])
def test_translated_cleanup_stops_children_even_after_leader_exit(monkeypatch, tmp_path, leader_exits_first):
    child_pid = tmp_path / "child.pid"
    leader = tmp_path / "leader.py"
    # The child ignores SIGTERM so cleanup must escalate even if the leader
    # exits first. It inherits the leader's new process group.
    leader.write_text(
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', "
        "'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'])\n"
        "time.sleep(0.1)\n"
        f"open({str(child_pid)!r}, 'w').write(str(child.pid))\n"
        + ("\n" if leader_exits_first else "time.sleep(60)\n"),
        encoding="utf-8",
    )
    owner = ServerSupervisor(
        RuntimeSettings.from_env({"ASA_TRANSLATOR_MODE": "none", "ASA_SHUTDOWN_TIMEOUT": "1"}),
        logging.getLogger("process-test"),
    )
    owner.execution_context = replace(owner.execution_context, translator_mode="fex")
    monkeypatch.setattr("server_runtime.supervisor.PID_FILE", str(tmp_path / "server.pid"))
    process = subprocess.Popen([sys.executable, str(leader)], start_new_session=True)
    owner.server_process = process
    try:
        wait_for_file(child_pid, process)
        pid = int(child_pid.read_text())
        if leader_exits_first:
            process.wait(timeout=5)
        else:
            owner._stop_server_process(process)
        owner._cleanup_after_run()
        process.wait(timeout=5)
        deadline = time.monotonic() + 2
        while is_running(pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not is_running(pid), "A translated server child survived cleanup"
    finally:
        # Keep a failing regression test from leaking its own fixture processes.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)
