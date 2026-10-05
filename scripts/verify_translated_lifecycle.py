"""Verify translated supervisor restart, signal delivery and process cleanup.

Called by verify_arm64_translation after its real SteamCMD and Proton checks.
Guest Python fixtures test graceful and stubborn children; a real Windows command
process tests the Proton/FEX process tree. Only game preparation and RCON are
replaced: supervisor signals, save delay, restart and cleanup stay in production.
"""

from __future__ import annotations

from dataclasses import replace
import json
import logging
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time


SCRIPT = Path(__file__).resolve()
TOKEN_ENV = "ASA_TRANSLATED_LIFECYCLE_TOKEN"
GENERATION_ENV = "ASA_TRANSLATED_LIFECYCLE_GENERATION"
_fex_server = shutil.which("FEXServer")
FEX_SERVER = Path(_fex_server).resolve() if _fex_server else None


def record(root: Path, kind: str, **values: object) -> None:
    with (root / "events.jsonl").open("a", encoding="utf-8") as output:
        output.write(json.dumps({"kind": kind, "time": time.monotonic(), **values}) + "\n")


def events(root: Path) -> list[dict]:
    path = root / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def living_processes(root: Path, generation: int | None = None) -> list[int]:
    """Find fixture processes by inherited environment, ignoring exited zombies."""
    token = f"{TOKEN_ENV}={root}".encode()
    selected = f"{GENERATION_ENV}={generation}".encode() if generation is not None else None
    found = []
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        try:
            # comm can contain spaces or parentheses; state follows its final ')'.
            state = (path / "stat").read_text().rsplit(")", 1)[1].split()[0]
            environment = (path / "environ").read_bytes().split(b"\0")
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        if state != "Z" and token in environment and (selected is None or selected in environment):
            # FEXServer is shared across translated commands, not owned by a
            # server launch. Audit every guest/Wine process, excluding only the
            # actual installed daemon executable rather than a process name.
            if FEX_SERVER is not None:
                try:
                    if Path(os.readlink(path / "exe")).resolve() == FEX_SERVER:
                        continue
                except FileNotFoundError:
                    continue
                except PermissionError:
                    pass
            found.append(int(path.name))
    return found


def guest(root: Path, case: str, child: bool = False) -> None:
    generation = int(os.environ[GENERATION_ENV])
    stopped = False

    def stop(_signal: int, _frame: object) -> None:
        nonlocal stopped
        record(root, "terminated", generation=generation, child=child, pid=os.getpid())
        stopped = True

    if child and case == "guest-stubborn":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    else:
        signal.signal(signal.SIGTERM, stop)
    descendant = None
    if not child:
        descendant = subprocess.Popen([sys.executable, str(SCRIPT), "--guest-child", case, str(root)])
    record(root, "child-started" if child else "started", generation=generation, pid=os.getpid())
    while not stopped:
        time.sleep(0.05)
    if descendant is not None and case == "guest-graceful":
        descendant.wait(timeout=5)


def supervisor(root: Path, case: str, version: str, native_fixture: bool = False) -> None:
    from server_runtime import launch_env
    from server_runtime import proton as proton_runtime
    from server_runtime import supervisor as runtime
    from server_runtime.constants import RuntimeSettings
    from server_runtime.proton import ORIGIN_PINNED, ProtonSelection
    from server_runtime.translation import ExecutionContext, wrap_command

    runtime.PID_FILE = str(root / "server.pid")
    runtime.SUPERVISOR_PID_FILE = str(root / "supervisor.pid")
    runtime.ASA_BINARY_DIR = str(root)
    runtime.LOG_DIR = str(root / "logs")
    launch_env.ASA_COMPAT_DATA = str(root / "prefix")
    runtime.update_server_files = lambda *_args, **_kwargs: None
    runtime.probe_steamcmd_translation = lambda *_args: None
    runtime.prepare_proton = lambda *_args, **_kwargs: ProtonSelection(version, ORIGIN_PINNED)
    if case == "proton":
        proton_runtime.ASA_COMPAT_DATA = launch_env.ASA_COMPAT_DATA
        proton_runtime.STEAM_COMPAT_DATA = str(root)
        runtime.ensure_proton_compat_data = proton_runtime.ensure_proton_compat_data
    else:
        (root / "prefix").mkdir()
        runtime.ensure_proton_compat_data = lambda *_args: None
        runtime.stop_proton_session = lambda *_args, **_kwargs: None
    runtime.resolve_launch_binary = lambda *_args: "cmd.exe"
    runtime.prepare_start_params = lambda *_args: "Map?listen"
    if native_fixture:
        # Exercise translated supervisor policy with native fixtures on x86 CI.
        # This runner deliberately provides no evidence about FEX itself.
        runtime.resolve_execution_context = lambda *_args: ExecutionContext(
            architecture="amd64", translator_mode="fex", runner_prefix=("/bin/sh", "-c"),
            wraps_with_shell=True, probe_timeout=60,
        )

    class FixtureSupervisor(runtime.ServerSupervisor):
        generation = 0

        def _build_launch_command(self, proton_dir_name: str, launch_binary: str, params: str) -> list[str]:
            self.generation += 1
            self.server_env[TOKEN_ENV] = str(root)
            self.server_env[GENERATION_ENV] = str(self.generation)
            if case.startswith("guest-"):
                interpreter = sys.executable if native_fixture else "/usr/bin/python3"
                command = wrap_command(self.execution_context, [interpreter, str(SCRIPT), "--guest", case, str(root)])
            else:
                windows_marker = "Z:" + str(root / "heartbeat.txt").replace("/", "\\")
                # Keep a real Windows child alive well beyond the readiness
                # marker, using the same cmd.exe /c path as the execution smoke.
                params = shlex.join(["/c", f"echo {self.generation} >{windows_marker} & ping -n 300 127.0.0.1 >nul"])
                command = super()._build_launch_command(proton_dir_name, launch_binary, params)
            record(root, "launch", generation=self.generation, command=command)
            return command

        def _send_saveworld(self) -> bool:
            record(root, "saveworld", generation=self.generation)
            return True

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = replace(
        RuntimeSettings.from_env(), server_restart_delay=0,
        shutdown_saveworld_delay=1, shutdown_timeout=3,
    )
    owner = FixtureSupervisor(settings, logging.getLogger("translated-lifecycle"))
    owner.register_supervisor_pid()
    try:
        result = owner.run()
    finally:
        owner.cleanup()
    # Wine and its wrapper may report SIGTERM as a nonzero exit status. Reaching
    # here proves run() completed its requested shutdown instead of being killed.
    record(root, "completed", result=result)


def wait_for(process: subprocess.Popen, predicate, seconds: float = 120) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        if process.poll() is not None:
            raise AssertionError(f"Supervisor exited before the lifecycle event: {process.returncode}")
        time.sleep(0.1)
    raise TimeoutError("Translated lifecycle event did not arrive")


def assert_no_processes(root: Path, generation: int | None = None) -> None:
    # A killed child may briefly remain runnable before Linux marks it a zombie.
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if not living_processes(root, generation):
            return
        time.sleep(0.05)
    raise AssertionError(f"Translated descendants remained alive: {living_processes(root, generation)}")


def process_details(root: Path) -> list[dict]:
    details = []
    for pid in living_processes(root):
        try:
            path = Path(f"/proc/{pid}")
            try:
                executable = os.readlink(path / "exe")
            except PermissionError:
                executable = "unavailable"
            details.append({"pid": pid, "group": os.getpgid(pid), "session": os.getsid(pid),
                            "executable": executable, "name": (path / "comm").read_text().strip(),
                            "command": (path / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")})
        except (ProcessLookupError, FileNotFoundError):
            pass
    return details


def verify_case(case: str, version: str, native_fixture: bool = False) -> None:
    with tempfile.TemporaryDirectory(prefix=f"asa-translated-{case}-") as temporary:
        root = Path(temporary)
        with (root / "supervisor.log").open("w+", encoding="utf-8") as output:
            process = subprocess.Popen(
                [sys.executable, str(SCRIPT), "--native-supervisor" if native_fixture else "--supervisor", case, str(root), version],
                stdout=output, stderr=output, start_new_session=True,
            )
            try:
                for generation in (1, 2):
                    if case.startswith("guest-"):
                        wait_for(process, lambda: any(item["kind"] == "child-started" and item["generation"] == generation for item in events(root)))
                    else:
                        def heartbeat() -> bool:
                            marker = root / "heartbeat.txt"
                            return marker.exists() and marker.read_text().strip() == str(generation)
                        wait_for(process, heartbeat)
                    assert living_processes(root, generation), "Fixture did not expose a tagged process tree"
                    if generation == 2:
                        assert_no_processes(root, 1)
                    process.send_signal(signal.SIGUSR1 if generation == 1 else signal.SIGTERM)
                assert process.wait(timeout=20) == 0
                assert any(item["kind"] == "completed" for item in events(root))
                assert sum(item["kind"] == "launch" for item in events(root)) == 2, "Unexpected extra server launch"
                assert_no_processes(root)
                assert not (root / "server.pid").exists()
                assert not (root / "supervisor.pid").exists()
                if case.startswith("guest-"):
                    current = events(root)
                    for generation in (1, 2):
                        saved = next(item for item in current if item["kind"] == "saveworld" and item["generation"] == generation)
                        stopped = next(item for item in current if item["kind"] == "terminated" and not item["child"] and item["generation"] == generation)
                        assert stopped["time"] - saved["time"] >= 0.9, "Save delay was skipped"
                        child_stops = [item for item in current if item["kind"] == "terminated" and item["child"] and item["generation"] == generation]
                        assert bool(child_stops) == (case == "guest-graceful"), "Unexpected child signal behavior"
            except Exception:
                output.flush()
                print((root / "supervisor.log").read_text(), file=sys.stderr)
                marker = root / "heartbeat.txt"
                print({"events": events(root), "marker": marker.read_bytes() if marker.exists() else None,
                       "living_processes": process_details(root)}, file=sys.stderr)
                raise
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                # Failure cleanup never satisfies the earlier orphan assertions.
                for pid in living_processes(root):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        print(f"PASS {case}: translated restart, save delay, shutdown and no living descendants.", flush=True)


def verify_translated_lifecycle(proton, context) -> None:
    if context.architecture != "arm64" or context.translator_mode != "fex":
        raise RuntimeError("Translated acceptance requires native ARM64 and FEX.")
    for case in ("guest-graceful", "guest-stubborn", "proton"):
        verify_case(case, proton.version)


if __name__ == "__main__":
    if sys.argv[1:] == ["--native-fixture"]:
        if sys.platform != "linux":
            raise SystemExit("Native lifecycle fixtures require Linux.")
        for case in ("guest-graceful", "guest-stubborn"):
            verify_case(case, "fixture", native_fixture=True)
        print("Native fixture checks passed; FEX and Proton were not exercised.")
        raise SystemExit(0)
    mode, case, root = sys.argv[1:4]
    if mode in {"--supervisor", "--native-supervisor"}:
        supervisor(Path(root), case, sys.argv[4], native_fixture=mode == "--native-supervisor")
    elif mode in {"--guest", "--guest-child"}:
        guest(Path(root), case, child=mode == "--guest-child")
    else:
        raise SystemExit("Invoke this check through verify_arm64_translation.py")
