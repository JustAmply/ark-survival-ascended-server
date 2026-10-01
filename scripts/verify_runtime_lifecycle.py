"""Exercise the Linux supervisor with real children, signals and TCP RCON.

Run in the built image as gameserver with this file mounted read-only. SteamCMD,
Proton installation and the game binary are replaced at their external seams.
The production launch environment, scheduler, RCON client and shutdown run
unchanged, except for an accelerated scheduler clock. No ARK download or
existing server volume is needed. This is not a full game-server acceptance test.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import shlex
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta


SCRIPT = Path(__file__).resolve()


def record(root: Path, kind: str, **values: object) -> None:
    with (root / "events.jsonl").open("a", encoding="utf-8") as output:
        output.write(json.dumps({"kind": kind, "time": time.monotonic(), **values}) + "\n")


def events(root: Path) -> list[dict]:
    path = root / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def receive_exact(connection: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        part = connection.recv(size - len(data))
        if not part:
            raise EOFError
        data += part
    return data


def game(root: Path) -> None:
    from asa_ctrl.common.config import AsaSettings

    settings = AsaSettings()
    discrete = os.environ["ASA_LIFECYCLE_CASE"] == "discrete"
    password = "test-private-password" if discrete else "changeme"
    configured_password = settings.get_start_param_value("ServerAdminPassword") or settings.get_server_setting("ServerAdminPassword")
    assert configured_password == password, "Game did not receive the expected fixture credential"
    port = int(settings.get_start_param_value("RCONPort"))
    assert password
    assert "STEAM_COMPAT_DATA_PATH" in os.environ
    assert os.environ["SDL_VIDEODRIVER"] == "dummy"
    assert (Path(os.environ["XDG_RUNTIME_DIR"]).stat().st_mode & 0o777) == 0o700
    assert sys.argv[3:] == ["run", "ArkAscendedServer.exe", *shlex.split(os.environ["ASA_START_PARAMS"])]
    # The INI is a fixed fixture, never assembled from environment credentials.
    ini_fixture = (
        "[ServerSettings]\nServerAdminPassword=test-private-password\n"
        if discrete else "[ServerSettings]\nServerAdminPassword=changeme\n"
    )
    Path(os.environ["ASA_GAME_USER_SETTINGS_PATH"]).write_text(
        ini_fixture + f"RCONPort={port}\n", encoding="utf-8"
    )
    running = True

    def stop(_sig: int, _frame: object) -> None:
        nonlocal running
        record(root, "terminated", pid=os.getpid())
        running = False

    signal.signal(signal.SIGTERM, stop)
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", port))
        listener.listen()
        listener.settimeout(0.1)
        record(root, "started", pid=os.getpid(), uid=os.getuid())
        while running:
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            with connection:
                connection.settimeout(2)
                authenticated = False
                try:
                    while running:
                        size = struct.unpack("<I", receive_exact(connection, 4))[0]
                        payload = receive_exact(connection, size)
                        packet_id, packet_type = struct.unpack("<ii", payload[:8])
                        body = payload[8:-2].decode()
                        if packet_type == 3:
                            authenticated = body == password
                            response_id = packet_id if authenticated else -1
                            response_type = 2
                        else:
                            assert authenticated, "Command received without valid RCON authentication"
                            record(root, "rcon", command=body, pid=os.getpid())
                            response_id, response_type = packet_id, 0
                        response = struct.pack("<ii", response_id, response_type) + b"ok\0\0"
                        connection.sendall(struct.pack("<I", len(response)) + response)
                except (EOFError, socket.timeout):
                    pass


def scheduler(root: Path) -> None:
    from asa_ctrl import cli
    from asa_ctrl.core import restart_scheduler

    assert "STEAM_COMPAT_DATA_PATH" not in os.environ
    assert "SDL_VIDEODRIVER" not in os.environ
    assert os.environ["SERVER_RESTART_WARNINGS"] == "1"
    deadline = time.monotonic() + 10
    while not any(item["kind"] == "started" for item in events(root)):
        if time.monotonic() > deadline:
            raise TimeoutError("Server did not start before scheduler")
        time.sleep(0.02)
    started = time.monotonic()

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 1, 1, 0, 0, 58) + timedelta(
                seconds=(time.monotonic() - started) * 60
            )

    class Timer:
        @staticmethod
        def sleep(seconds: float) -> None:
            time.sleep(seconds / 60)

    restart_scheduler.datetime = Clock
    restart_scheduler.time = Timer
    record(root, "scheduler", pid=os.getpid())
    cli.main(["restart-scheduler"])


def supervisor(root: Path) -> None:
    from server_runtime import launch_env
    from server_runtime import supervisor as runtime
    from server_runtime.constants import RuntimeSettings
    from server_runtime.proton import ORIGIN_PINNED, ProtonSelection

    runtime.PID_FILE = launch_env.PID_FILE = str(root / "server.pid")
    runtime.SUPERVISOR_PID_FILE = launch_env.SUPERVISOR_PID_FILE = str(root / "supervisor.pid")
    runtime.STEAM_COMPAT_DIR = str(root / "proton")
    runtime.ASA_BINARY_DIR = str(root)
    runtime.LOG_DIR = str(root / "logs")
    runtime.ASA_CTRL_BIN = str(root / "scheduler")
    runtime.update_server_files = lambda *_: None
    runtime.ensure_proton_compat_data = lambda *_: None
    runtime.resolve_launch_binary = lambda *_: "ArkAscendedServer.exe"

    def prepare(_logger, _settings, previous=None):
        if previous is None:
            record(root, "proton_selection")
        return previous or ProtonSelection("test", ORIGIN_PINNED)

    runtime.prepare_proton = prepare
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    owner = runtime.ServerSupervisor(RuntimeSettings.from_env(), logging.getLogger("lifecycle"))
    original_environment = dict(os.environ)
    owner.register_supervisor_pid()
    owner.start_restart_scheduler()
    try:
        code = owner.run()
        assert os.environ == original_environment, "Child environment leaked into supervisor"
    finally:
        owner.cleanup()
    raise SystemExit(code)


def wait_for(root: Path, process: subprocess.Popen, predicate, seconds: float = 15) -> list[dict]:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        current = events(root)
        if predicate(current):
            return current
        if process.poll() is not None:
            raise AssertionError(f"Supervisor exited early: {process.returncode}")
        time.sleep(0.02)
    raise TimeoutError("Lifecycle event did not arrive")


def verify_case(case: str) -> None:
    with tempfile.TemporaryDirectory(prefix=f"asa-lifecycle-{case}-") as temporary:
        root = Path(temporary)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        env = {key: value for key, value in os.environ.items() if not key.startswith("ASA_")}
        for key in ("STEAM_COMPAT_DATA_PATH", "SDL_VIDEODRIVER", "PROTON_VERSION"):
            env.pop(key, None)
        env.update(
            ASA_LIFECYCLE_CASE=case,
            ASA_GAME_USER_SETTINGS_PATH=str(root / "GameUserSettings.ini"),
            ASA_MOD_DATABASE_PATH=str(root / "mods.json"),
            SERVER_RESTART_CRON="2 0 * * *",
            SERVER_RESTART_WARNINGS="1",
            SERVER_RESTART_DELAY="0",
            ASA_SHUTDOWN_SAVEWORLD_DELAY="1",
            ASA_SHUTDOWN_TIMEOUT="3",
        )
        if case == "discrete":
            env.update(ASA_MAP="Map", ASA_RCON_PORT=str(port), ASA_SERVER_ADMIN_PASSWORD="test-private-password")
        else:
            env["ASA_START_PARAMS"] = f"Map?listen?RCONPort={port}?RCONEnabled=True"
        for path, mode in ((root / "scheduler", "scheduler"), (root / "proton/GE-Protontest/proton", "game")):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"#!/bin/sh\nexec {sys.executable} {SCRIPT} {mode} {root} \"$@\"\n", encoding="utf-8"
            )
            path.chmod(0o755)
        with (root / "supervisor.log").open("w+", encoding="utf-8") as output:
            process = subprocess.Popen([sys.executable, str(SCRIPT), "supervisor", str(root)], env=env, stdout=output, stderr=output)
            try:
                current = wait_for(root, process, lambda items: sum(item["kind"] == "started" for item in items) >= 2)
                assert any(item.get("command", "").startswith("serverchat Server restart in 1 minute") for item in current)
                assert any(item.get("command", "").startswith("serverchat Server restarting now") for item in current)
                process.terminate()
                assert process.wait(timeout=10) == 0
            except Exception:
                output.flush()
                print((root / "supervisor.log").read_text(encoding="utf-8"), file=sys.stderr)
                print(events(root), file=sys.stderr)
                raise
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                output.seek(0)
                log = output.read()
            current = events(root)
            launches = [item for item in current if item["kind"] == "started"]
            assert len(launches) == 2, current
            assert all(item["uid"] == 25000 for item in launches)
            assert sum(item["kind"] == "proton_selection" for item in current) == 1
            for launch in launches:
                saved = next(item for item in current if item.get("command") == "saveworld" and item["pid"] == launch["pid"])
                stopped = next(item for item in current if item["kind"] == "terminated" and item["pid"] == launch["pid"])
                assert stopped["time"] - saved["time"] >= 0.9, "Save delay was skipped"
                try:
                    os.kill(launch["pid"], 0)
                except ProcessLookupError:
                    pass
                else:
                    raise AssertionError("Server child remains after shutdown")
            scheduler_pid = next(item["pid"] for item in current if item["kind"] == "scheduler")
            try:
                os.kill(scheduler_pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError("Scheduler remains after shutdown")
            assert not (root / "server.pid").exists()
            assert not (root / "supervisor.pid").exists()
            if "<redacted>" in log:
                assert "test-private-password" not in log
                assert "ServerAdminPassword=changeme" not in log
            print(f"PASS {case}: warnings, authenticated RCON, save delay, restart, shutdown and cleanup")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        {"game": game, "scheduler": scheduler, "supervisor": supervisor}[sys.argv[1]](Path(sys.argv[2]))
    else:
        if not hasattr(signal, "SIGUSR1") or os.getuid() != 25000:
            raise SystemExit("Run this Linux image check as gameserver (UID 25000)")
        for case_name in ("discrete", "legacy-fallback"):
            verify_case(case_name)
        print("Runtime lifecycle smoke test passed. ARK itself was not launched.")
