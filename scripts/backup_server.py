"""Offline Docker server backups with verified, non-overwriting recovery."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import uuid
import zipfile


FORMAT = "asa-offline-backup-v1"
SERVER_PATH = "/home/gameserver/server-files"
CLUSTER_PATH = "/home/gameserver/cluster-shared"


def docker(*arguments: str) -> str:
    return subprocess.run(
        ["docker", *arguments], check=True, capture_output=True, text=True,
    ).stdout


def inspect_containers(names: list[str]) -> list[dict]:
    return json.loads(docker("inspect", *names)) if names else []


def data_mount(container: dict, destination: str) -> dict:
    for mount in container["Mounts"]:
        if mount["Destination"] == destination:
            return mount
    raise ValueError(f"{container['Name']} needs a mount at {destination}")


def require_stopped(containers: list[dict], allowed_running: set[str] | None = None) -> None:
    """Check every container sharing the selected mounts, including other stacks."""
    sources = {
        data_mount(container, destination)["Source"]
        for container in containers for destination in (SERVER_PATH, CLUSTER_PATH)
    }
    all_ids = docker("ps", "-aq").split()
    for container in inspect_containers(all_ids):
        shares_data = any(
            PurePosixPath(mount["Source"]).is_relative_to(source)
            or PurePosixPath(source).is_relative_to(mount["Source"])
            for mount in container["Mounts"] for source in sources
        )
        if shares_data and container["State"]["Running"] and container["Id"] not in (allowed_running or set()):
            raise ValueError(f"Stop {container['Name']} before backing up shared data")


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def write_archive(staging: Path, archive: Path, metadata: dict) -> None:
    files = {}
    directories = []
    for path in sorted(staging.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Backup data contains a symbolic link: {path}")
        name = path.relative_to(staging).as_posix()
        if path.is_dir():
            directories.append(name)
        elif path.is_file():
            files[name] = {"sha256": digest(path), "size": path.stat().st_size}
        else:
            raise ValueError(f"Unsupported backup file: {path}")
    manifest = {"format": FORMAT, "files": files, "directories": directories, **metadata}
    archive.touch(mode=0o600, exist_ok=False)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for name in files:
            output.write(staging / name, name)
        output.writestr("manifest.json", json.dumps(manifest, indent=2))


def safe_name(name: str) -> bool:
    if not isinstance(name, str):
        return False
    path = PurePosixPath(name)
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    return bool(name) and not path.is_absolute() and all(
        part not in ("", ".", "..") and ":" not in part and "\\" not in part
        and not part.endswith((".", " ")) and part.split(".")[0].upper() not in reserved
        for part in name.split("/")
    )


def verify_archive(archive: Path) -> dict:
    with zipfile.ZipFile(archive) as source:
        manifest = json.loads(source.read("manifest.json"))
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
            raise ValueError("Unsupported backup format")
        files = manifest["files"]
        directories = manifest["directories"]
        if not isinstance(files, dict) or not isinstance(directories, list):
            raise ValueError("Invalid backup manifest")
        names = source.namelist()
        if len(names) != len(set(names)) or set(names) != {"manifest.json", *files}:
            raise ValueError("Archive members differ from the manifest")
        for name in [*files, *directories]:
            if not safe_name(name) or name == "manifest.json":
                raise ValueError(f"Unsafe archive path: {name}")
        paths = [*files, *directories]
        if len({name.casefold() for name in paths}) != len(paths):
            raise ValueError("Duplicate or case-colliding backup paths")
        for name, expected in files.items():
            if not isinstance(expected, dict) or not isinstance(expected.get("sha256"), str):
                raise ValueError(f"Invalid file metadata: {name}")
            if source.getinfo(name).file_size != expected["size"]:
                raise ValueError(f"Size mismatch: {name}")
            with source.open(name) as entry:
                actual = hashlib.file_digest(entry, "sha256").hexdigest()
            if actual != expected["sha256"]:
                raise ValueError(f"Checksum mismatch: {name}")
    return manifest


def restore_archive(archive: Path, destination: Path) -> None:
    manifest = verify_archive(archive)
    # Creating exclusively protects existing worlds, including an empty destination.
    destination.mkdir(parents=False, exist_ok=False, mode=0o700)
    try:
        with zipfile.ZipFile(archive) as source:
            for name in manifest["directories"]:
                (destination / name).mkdir(parents=True, exist_ok=True)
            for name in manifest["files"]:
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(name) as entry, target.open("xb") as output:
                    shutil.copyfileobj(entry, output)
                if digest(target) != manifest["files"][name]["sha256"]:
                    raise ValueError(f"Restored file failed verification: {name}")
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except Exception:
        # Only our exclusively created destination is eligible for cleanup.
        shutil.rmtree(destination)
        raise


def prune_backups(directory: Path, keep: int) -> None:
    candidates = []
    for path in directory.glob("asa-backup-*.zip"):
        try:
            verify_archive(path)
        except (ValueError, KeyError, OSError, zipfile.BadZipFile):
            continue
        candidates.append(path)
    for path in sorted(candidates, reverse=True)[keep:]:
        path.unlink()


def create_backup(names: list[str], directory: Path, includes: list[Path], keep: int) -> Path:
    if keep < 1:
        raise ValueError("Retention must keep at least one backup")
    containers = inspect_containers(names)
    if not containers or len({container["Id"] for container in containers}) != len(containers):
        raise ValueError("Select at least one container, without duplicates")
    require_stopped(containers)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    archive = directory / f"asa-backup-{stamp}-{uuid.uuid4().hex[:8]}.zip"
    temporary_archive = archive.with_suffix(".partial")
    try:
        with tempfile.TemporaryDirectory(prefix="asa-backup-") as temporary:
            staging = Path(temporary)
            clusters = {}
            entries = []
            for index, container in enumerate(containers):
                server_dir = staging / "servers" / str(index)
                server_dir.mkdir(parents=True)
                # Copy the small persistent subtree, not downloadable binaries/Proton.
                docker("cp", f"{container['Id']}:{SERVER_PATH}/ShooterGame/Saved", str(server_dir / "Saved"))
                docker("cp", f"{container['Id']}:{SERVER_PATH}/mods.json", str(server_dir / "mods.json"))
                cluster_source = data_mount(container, CLUSTER_PATH)["Source"]
                if cluster_source not in clusters:
                    cluster_name = f"clusters/{len(clusters)}"
                    clusters[cluster_source] = cluster_name
                    (staging / "clusters").mkdir(exist_ok=True)
                    docker("cp", f"{container['Id']}:{CLUSTER_PATH}", str(staging / cluster_name))
                entries.append({"name": container["Name"].lstrip("/"), "data": f"servers/{index}", "cluster": clusters[cluster_source]})
            for index, path in enumerate(includes):
                if not path.is_file() or path.is_symlink():
                    raise ValueError(f"Included configuration must be a regular file: {path}")
                target = staging / "configuration" / str(index) / path.name
                target.parent.mkdir(parents=True)
                shutil.copyfile(path, target)
            require_stopped(containers)
            write_archive(staging, temporary_archive, {"created_at": stamp, "servers": entries})
            verify_archive(temporary_archive)
            temporary_archive.rename(archive)
        prune_backups(directory, keep)
        return archive
    finally:
        temporary_archive.unlink(missing_ok=True)


def maintenance_backup(
    names: list[str], directory: Path, includes: list[Path], keep: int, stop_timeout: int,
) -> Path:
    """Stop selected running servers and restore their original running state."""
    if stop_timeout < 1 or keep < 1:
        raise ValueError("Stop timeout and retention must be positive")
    containers = inspect_containers(names)
    running = [container["Id"] for container in containers if container["State"]["Running"]]
    # Never stop an unrelated peer implicitly, or stop our servers only to discover
    # that another running cluster member makes a consistent snapshot impossible.
    require_stopped(containers, allowed_running=set(running))
    try:
        if running:
            docker("stop", "--time", str(stop_timeout), *running)
        return create_backup(names, directory, includes, keep)
    finally:
        if running:
            # A partially failed stop may already have stopped some containers.
            # Docker start is also safe for selected containers still running.
            docker("start", *running)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup", help="Back up stopped containers sharing persistent data")
    backup.add_argument("--container", action="append", required=True)
    backup.add_argument("--directory", type=Path, required=True)
    backup.add_argument("--include", type=Path, action="append", default=[])
    backup.add_argument("--keep", type=int, default=7)
    backup.add_argument("--stop", action="store_true", help="Stop selected running containers and restart them afterwards")
    backup.add_argument("--stop-timeout", type=int, default=300, help="Graceful stop timeout in seconds with --stop (default: 300)")
    verify = commands.add_parser("verify", help="Read and checksum every archived file")
    verify.add_argument("archive", type=Path)
    restore = commands.add_parser("restore", help="Restore into a new directory and verify every file")
    restore.add_argument("archive", type=Path)
    restore.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "backup":
            if args.stop:
                print(maintenance_backup(args.container, args.directory, args.include, args.keep, args.stop_timeout))
            else:
                print(create_backup(args.container, args.directory, args.include, args.keep))
        elif args.command == "verify":
            verify_archive(args.archive)
            print("Backup verified.")
        else:
            restore_archive(args.archive, args.destination)
            print(f"Restored and verified: {args.destination}")
    except (ValueError, OSError, KeyError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Backup operation failed: {error}\n")


if __name__ == "__main__":
    main()
