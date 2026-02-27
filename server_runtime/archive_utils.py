"""Archive extraction helpers shared across runtime modules."""

from __future__ import annotations

import tarfile
from pathlib import Path


def safe_extract_tar(tar: tarfile.TarFile, destination: Path) -> None:
    """Safely extract a tar archive, preventing path traversal."""
    dest_root = destination.resolve()
    members = tar.getmembers()
    for member in members:
        if member.isdev() or member.isfifo():
            raise RuntimeError(f"Unsupported tar special member detected: {member.name!r}")

        member_path = (dest_root / member.name).resolve()
        if member_path != dest_root and dest_root not in member_path.parents:
            raise RuntimeError(f"Unsafe tar member path detected: {member.name!r}")

        if member.issym():
            link_target = (member_path.parent / member.linkname).resolve()
            if link_target != dest_root and dest_root not in link_target.parents:
                raise RuntimeError(
                    f"Unsafe tar link target detected: {member.name!r} -> {member.linkname!r}"
                )
        elif member.islnk():
            link_target = (dest_root / member.linkname).resolve()
            if link_target != dest_root and dest_root not in link_target.parents:
                raise RuntimeError(
                    f"Unsafe tar link target detected: {member.name!r} -> {member.linkname!r}"
                )

    tar.extractall(dest_root, members=members)
