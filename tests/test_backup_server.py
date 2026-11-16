"""Offline backup integrity and non-overwriting recovery contracts."""

import importlib.util
import json
from pathlib import Path
import zipfile

import pytest


spec = importlib.util.spec_from_file_location(
    "backup_server", Path(__file__).resolve().parents[1] / "scripts" / "backup_server.py"
)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def archive_fixture(tmp_path, name="asa-backup-20260101.zip"):
    staging = tmp_path / "staging"
    staging.mkdir(exist_ok=True)
    (staging / "servers/0/Saved/Config").mkdir(parents=True, exist_ok=True)
    (staging / "servers/0/Saved/world.ark").write_bytes(b"world-save\x00\xff")
    (staging / "servers/0/mods.json").write_text("[]")
    (staging / "clusters/0").mkdir(parents=True, exist_ok=True)
    (staging / "clusters/0/transfer.arkprofile").write_bytes(b"transfer")
    archive = tmp_path / name
    backup.write_archive(staging, archive, {"servers": [{"name": "test"}]})
    return archive


def test_roundtrip_restores_world_cluster_mods_and_empty_configuration(tmp_path):
    archive = archive_fixture(tmp_path)
    destination = tmp_path / "recovery"
    backup.restore_archive(archive, destination)
    assert (destination / "servers/0/Saved/world.ark").read_bytes() == b"world-save\x00\xff"
    assert (destination / "servers/0/mods.json").read_text() == "[]"
    assert (destination / "servers/0/Saved/Config").is_dir()
    assert (destination / "clusters/0/transfer.arkprofile").read_bytes() == b"transfer"
    assert json.loads((destination / "manifest.json").read_text())["servers"] == [{"name": "test"}]


def test_restore_never_overwrites_existing_destination(tmp_path):
    archive = archive_fixture(tmp_path)
    destination = tmp_path / "existing"
    destination.mkdir()
    sentinel = destination / "world.ark"
    sentinel.write_bytes(b"current world")
    with pytest.raises(FileExistsError):
        backup.restore_archive(archive, destination)
    assert sentinel.read_bytes() == b"current world"


def rewrite_archive(archive, mutate):
    with zipfile.ZipFile(archive) as source:
        entries = {name: source.read(name) for name in source.namelist()}
    mutate(entries)
    with zipfile.ZipFile(archive, "w") as output:
        for name, content in entries.items():
            output.writestr(name, content)


def test_tampered_backup_rejected_before_creating_destination(tmp_path):
    archive = archive_fixture(tmp_path)
    rewrite_archive(archive, lambda entries: entries.update({"servers/0/mods.json": b"{}"}))
    with pytest.raises(ValueError, match="Checksum mismatch"):
        backup.restore_archive(archive, tmp_path / "recovery")
    assert not (tmp_path / "recovery").exists()


@pytest.mark.parametrize("path", ["../escape", "/absolute", "C:/drive", "a\\escape", "safe/../escape", "NUL", "file. "])
def test_unsafe_manifest_paths_rejected(tmp_path, path):
    archive = archive_fixture(tmp_path)
    def mutate(entries):
        manifest = json.loads(entries["manifest.json"])
        manifest["directories"].append(path)
        entries["manifest.json"] = json.dumps(manifest).encode()
    rewrite_archive(archive, mutate)
    with pytest.raises(ValueError, match="Unsafe archive path"):
        backup.restore_archive(archive, tmp_path / "recovery")
    assert not (tmp_path / "recovery").exists()


def test_extra_unmanifested_file_rejected(tmp_path):
    archive = archive_fixture(tmp_path)
    rewrite_archive(archive, lambda entries: entries.update({"extra": b"unexpected"}))
    with pytest.raises(ValueError, match="members differ"):
        backup.verify_archive(archive)


def container(name, running, server="/vol/server", cluster="/vol/cluster"):
    return {"Id": name, "Name": name, "State": {"Running": running}, "Mounts": [
        {"Destination": backup.SERVER_PATH, "Source": server},
        {"Destination": backup.CLUSTER_PATH, "Source": cluster},
    ]}


def test_backup_refuses_running_cluster_peer_in_other_project(monkeypatch):
    selected = container("selected", False)
    peer = container("other-project-peer", True, server="/vol/other")
    monkeypatch.setattr(backup, "docker", lambda *args: "selected other-project-peer")
    monkeypatch.setattr(backup, "inspect_containers", lambda names: [selected, peer])
    with pytest.raises(ValueError, match="Stop other-project-peer"):
        backup.require_stopped([selected])


def test_backup_refuses_running_writer_with_overlapping_bind_mount(monkeypatch):
    selected = container("selected", False)
    peer = container("parent-mount-writer", True, server="/vol", cluster="/unrelated")
    monkeypatch.setattr(backup, "docker", lambda *args: "selected parent-mount-writer")
    monkeypatch.setattr(backup, "inspect_containers", lambda names: [selected, peer])
    with pytest.raises(ValueError, match="Stop parent-mount-writer"):
        backup.require_stopped([selected])


def test_retention_keeps_latest_valid_archives_and_unrelated_files(tmp_path):
    old = archive_fixture(tmp_path, "asa-backup-20260101.zip")
    new = archive_fixture(tmp_path, "asa-backup-20260102.zip")
    invalid = tmp_path / "asa-backup-unrelated.zip"
    invalid.write_bytes(b"not ours")
    backup.prune_backups(tmp_path, 1)
    assert not old.exists()
    assert new.exists() and invalid.read_bytes() == b"not ours"


def test_failed_restore_cleans_only_new_destination(tmp_path, monkeypatch):
    archive = archive_fixture(tmp_path)
    monkeypatch.setattr(backup, "digest", lambda path: "wrong")
    with pytest.raises(ValueError, match="Restored file failed"):
        backup.restore_archive(archive, tmp_path / "recovery")
    assert not (tmp_path / "recovery").exists()
    assert archive.exists()


def test_backup_deduplicates_cluster_and_verifies_before_pruning(tmp_path, monkeypatch):
    selected = [container("one", False), container("two", False, server="/vol/two")]
    monkeypatch.setattr(backup, "inspect_containers", lambda names: selected)
    checks = []
    monkeypatch.setattr(backup, "require_stopped", lambda containers: checks.append(True))
    copies = []
    def copy(*args):
        assert args[0] == "cp"
        copies.append(args[1])
        destination = Path(args[2])
        if args[1].endswith("mods.json"):
            destination.write_text("[]")
        else:
            destination.mkdir()
            (destination / "world").write_bytes(b"data")
        return ""
    monkeypatch.setattr(backup, "docker", copy)
    archive = backup.create_backup(["one", "two"], tmp_path / "backups", [], 2)
    manifest = backup.verify_archive(archive)
    assert len(checks) == 2
    assert sum(path.endswith(backup.CLUSTER_PATH) for path in copies) == 1
    assert manifest["servers"][0]["cluster"] == manifest["servers"][1]["cluster"]


def test_failed_copy_preserves_existing_backups(tmp_path, monkeypatch):
    archive = archive_fixture(tmp_path)
    monkeypatch.setattr(backup, "inspect_containers", lambda names: [container("one", False)])
    monkeypatch.setattr(backup, "require_stopped", lambda containers: None)
    def fail(*args):
        raise OSError("copy failed")
    monkeypatch.setattr(backup, "docker", fail)
    with pytest.raises(OSError, match="copy failed"):
        backup.create_backup(["one"], tmp_path, [], 1)
    assert archive.exists()
    assert not list(tmp_path.glob("*.partial"))


@pytest.mark.parametrize("fail_backup", [False, True])
def test_maintenance_restores_only_previously_running_containers(tmp_path, monkeypatch, fail_backup):
    selected = [container("running", True), container("stopped", False)]
    monkeypatch.setattr(backup, "inspect_containers", lambda names: selected)
    checks = []
    monkeypatch.setattr(backup, "require_stopped", lambda containers, **kwargs: checks.append(kwargs))
    calls = []
    monkeypatch.setattr(backup, "docker", lambda *args: calls.append(args))
    def create(*args):
        if fail_backup:
            raise ValueError("backup failed")
        return tmp_path / "archive.zip"
    monkeypatch.setattr(backup, "create_backup", create)
    if fail_backup:
        with pytest.raises(ValueError, match="backup failed"):
            backup.maintenance_backup(["running", "stopped"], tmp_path, [], 7, 300)
    else:
        assert backup.maintenance_backup(["running", "stopped"], tmp_path, [], 7, 300) == tmp_path / "archive.zip"
    assert checks == [{"allowed_running": {"running"}}]
    assert calls == [("stop", "--time", "300", "running"), ("start", "running")]


def test_maintenance_restarts_after_partial_stop_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "inspect_containers", lambda names: [container("running", True)])
    monkeypatch.setattr(backup, "require_stopped", lambda containers, **kwargs: None)
    calls = []
    def docker(*args):
        calls.append(args)
        if args[0] == "stop":
            raise OSError("stop failed")
    monkeypatch.setattr(backup, "docker", docker)
    with pytest.raises(OSError, match="stop failed"):
        backup.maintenance_backup(["running"], tmp_path, [], 7, 300)
    assert calls[-1] == ("start", "running")
