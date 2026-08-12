"""Safe archive extraction behind one runtime interface."""

from __future__ import annotations

import shutil
import stat
import tarfile
import zipfile
from pathlib import Path


def safe_extract_archive(
    archive: tarfile.TarFile | zipfile.ZipFile,
    destination: Path,
) -> None:
    """Extract a supported archive after validating all members."""
    dest_root = destination.resolve()
    dest_root.mkdir(parents=True, exist_ok=True)

    if isinstance(archive, tarfile.TarFile):
        _extract_tar(archive, dest_root)
        return
    if isinstance(archive, zipfile.ZipFile):
        _extract_zip(archive, dest_root)
        return
    raise TypeError(f"Unsupported archive type: {type(archive).__name__}")


def _extract_tar(archive: tarfile.TarFile, dest_root: Path) -> None:
    members = archive.getmembers()
    for member in members:
        if member.isdev() or member.isfifo():
            raise RuntimeError(f"Unsupported tar special member detected: {member.name!r}")

        member_path = _validated_target(dest_root, member.name, "tar")

        if member.issym():
            _validate_link_target(dest_root, member_path.parent, member.name, member.linkname)
        elif member.islnk():
            _validate_link_target(dest_root, dest_root, member.name, member.linkname)

    archive.extractall(dest_root, members=members)


def _extract_zip(archive: zipfile.ZipFile, dest_root: Path) -> None:
    members = archive.infolist()
    targets: list[tuple[zipfile.ZipInfo, Path]] = []
    for member in members:
        member_path = _validated_target(dest_root, member.filename, "zip")
        mode = member.external_attr >> 16
        file_type = stat.S_IFMT(mode)
        if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise RuntimeError(f"Unsupported zip special member detected: {member.filename!r}")
        targets.append((member, member_path))

    for member, member_path in targets:
        if member.is_dir() or member.filename.endswith("/"):
            member_path.mkdir(parents=True, exist_ok=True)
            continue

        member_path.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member, "r") as source, member_path.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)

        permissions = (member.external_attr >> 16) & 0o777
        if permissions:
            try:
                member_path.chmod(permissions)
            except OSError:
                pass


def _validated_target(dest_root: Path, member_name: str, archive_type: str) -> Path:
    member_path = (dest_root / member_name).resolve()
    if member_path != dest_root and dest_root not in member_path.parents:
        raise RuntimeError(f"Unsafe {archive_type} member path detected: {member_name!r}")
    return member_path


def _validate_link_target(
    dest_root: Path,
    link_root: Path,
    member_name: str,
    link_name: str,
) -> None:
    link_target = (link_root / link_name).resolve()
    if link_target != dest_root and dest_root not in link_target.parents:
        raise RuntimeError(
            f"Unsafe tar link target detected: {member_name!r} -> {link_name!r}"
        )
