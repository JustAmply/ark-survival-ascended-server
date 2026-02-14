"""Archive extraction helpers shared across runtime modules."""

from __future__ import annotations

import tarfile
from pathlib import Path


def safe_extract_tar(tar: tarfile.TarFile, destination: Path) -> None:
    """Safely extract a tar archive, preventing path traversal."""
    dest_root = destination.resolve()
    members = tar.getmembers()
    for member in members:
        target = (dest_root / member.name).resolve()
        if target != dest_root and dest_root not in target.parents:
            raise RuntimeError(f"Unsafe tar member path detected: {member.name!r}")
    tar.extractall(dest_root, members=members)
