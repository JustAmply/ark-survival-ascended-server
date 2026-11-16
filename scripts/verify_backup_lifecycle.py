"""Exercise offline backup and maintenance against disposable Docker fixtures.

Requires an available Docker daemon and a locally available Python 3.15 image.
Only this invocation's uniquely named, labelled containers and volumes are removed.
No ARK installation or existing server data is used.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import uuid


spec = importlib.util.spec_from_file_location(
    "backup_server", Path(__file__).resolve().with_name("backup_server.py")
)
assert spec is not None and spec.loader is not None
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)

FIXTURE_LABEL = "asa.backup-fixture"
SETUP = """
from pathlib import Path
import signal
import time

signal.signal(signal.SIGTERM, lambda *_: exit(0))
root = Path('/home/gameserver/server-files')
(root / 'ShooterGame/Saved/Config/WindowsServer').mkdir(parents=True, exist_ok=True)
(root / 'ShooterGame/Saved/world.ark').write_bytes(b'fixture-world')
(root / 'ShooterGame/Saved/Config/WindowsServer/Game.ini').write_text('[Fixture]')
(root / 'mods.json').write_text('[]')
Path('/home/gameserver/cluster-shared/transfer.arkprofile').write_bytes(b'fixture-transfer')
time.sleep(3600)
"""
PEER = "import signal,time; signal.signal(signal.SIGTERM, lambda *_: exit(0)); time.sleep(3600)"


def docker(*arguments: str) -> str:
    result = subprocess.run(
        ["docker", *arguments], check=True, capture_output=True, text=True,
    )
    return result.stdout


def running(name: str) -> bool:
    return json.loads(docker("inspect", name))[0]["State"]["Running"]


def exercise(names: list[str], root: Path) -> None:
    try:
        backup.create_backup([names[0]], root / "archives", [], 2)
    except ValueError as error:
        assert "Stop " in str(error)
    else:
        raise AssertionError("Running container accepted")

    try:
        backup.maintenance_backup([names[0]], root / "archives", [], 2, 10)
    except ValueError as error:
        assert names[1] in str(error)
    else:
        raise AssertionError("Running unselected peer accepted")
    assert running(names[0]), "Peer rejection stopped the selected server"

    docker("stop", "--time", "10", names[1])
    archive = backup.maintenance_backup([names[0]], root / "archives", [], 2, 10)
    assert running(names[0]), "Maintenance did not restart the selected server"
    assert not running(names[1]), "Maintenance started a previously stopped peer"
    backup.verify_archive(archive)
    backup.restore_archive(archive, root / "restore")
    assert (root / "restore/servers/0/Saved/world.ark").read_bytes() == b"fixture-world"
    assert (root / "restore/servers/0/mods.json").read_text() == "[]"
    assert (root / "restore/clusters/0/transfer.arkprofile").read_bytes() == b"fixture-transfer"
    try:
        backup.restore_archive(archive, root / "restore")
    except FileExistsError:
        pass
    else:
        raise AssertionError("Existing recovery overwritten")

    docker("stop", "--time", "10", names[0])
    backup.create_backup(names, root / "archives", [], 2)
    newest = backup.create_backup(names, root / "archives", [], 2)
    assert len(list((root / "archives").glob("asa-backup-*.zip"))) == 2
    manifest = backup.verify_archive(newest)
    assert len(manifest["servers"]) == 2
    assert len({entry["cluster"] for entry in manifest["servers"]}) == 1
    print(
        "PASS: running and peer rejection, maintenance restart state, stopped backup, "
        "SHA-256 verification, restored bytes, overwrite rejection, shared cluster and retention"
    )


def verify(image: str) -> None:
    # Keep network/pull policy in the invoking job, before allocating any fixtures.
    docker("image", "inspect", image)
    token = uuid.uuid4().hex
    prefix = f"codex-asa-backup-{token}"
    names = [f"{prefix}-server", f"{prefix}-peer"]
    volumes = [f"{prefix}-files", f"{prefix}-cluster"]
    created_containers: list[str] = []
    created_volumes: list[str] = []
    try:
        for volume in volumes:
            docker("volume", "create", "--label", f"{FIXTURE_LABEL}={token}", volume)
            created_volumes.append(volume)
        for index, name in enumerate(names):
            docker(
                "create", "--pull=never", "--name", name,
                "--entrypoint", "python", "--no-healthcheck",
                "--label", f"{FIXTURE_LABEL}={token}",
                "--mount", f"type=volume,source={volumes[0]},target={backup.SERVER_PATH}",
                "--mount", f"type=volume,source={volumes[1]},target={backup.CLUSTER_PATH}",
                image, "-c", SETUP if index == 0 else PEER,
            )
            created_containers.append(name)
            docker("start", name)
        docker("exec", names[0], "python", "-c", """
from pathlib import Path
import time
deadline = time.monotonic() + 10
while not Path('/home/gameserver/cluster-shared/transfer.arkprofile').exists():
    if time.monotonic() >= deadline:
        raise RuntimeError('Fixture did not initialize')
    time.sleep(0.05)
""")
        with tempfile.TemporaryDirectory(prefix="asa-backup-integration-") as directory:
            exercise(names, Path(directory))
    finally:
        failures = []
        for kind, created in (("container", created_containers), ("volume", created_volumes)):
            for name in reversed(created):
                try:
                    assert name.startswith(prefix + "-")
                    details = json.loads(docker(kind, "inspect", name))[0]
                    labels = details["Config"]["Labels"] if kind == "container" else details["Labels"]
                    if labels.get(FIXTURE_LABEL) != token:
                        raise RuntimeError(f"Refusing cleanup of unowned fixture {name}")
                    if kind == "container":
                        docker("container", "rm", "--force", name)
                    else:
                        docker("volume", "rm", name)
                except Exception as error:
                    failures.append(error)
        if failures:
            raise ExceptionGroup("Failed to clean backup fixtures", failures)
        print(f"Cleaned isolated fixtures: {prefix}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="python:3.15-slim", help="Existing local Python 3.15 fixture image")
    arguments = parser.parse_args()
    try:
        verify(arguments.image)
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"Docker fixture command failed: {error.stderr.strip()}") from error
