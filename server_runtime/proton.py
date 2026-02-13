"""GE-Proton resolution and installation helpers."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Optional

from .constants import (
    ASA_COMPAT_DATA,
    FALLBACK_PROTON_VERSION,
    PROTON_REPO,
    STEAM_COMPAT_DATA,
    STEAM_COMPAT_DIR,
)

_SAFE_VERSION_PATTERN = re.compile(r"^[0-9][0-9A-Za-z._-]*$")


def _fetch_json(url: str) -> Optional[Any]:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def _asset_exists(url: str) -> bool:
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=10):  # noqa: S310
            return True
    except urllib.error.HTTPError as exc:
        if exc.code == 405:
            # Some servers do not support HEAD.
            try:
                with urllib.request.urlopen(url, timeout=10):  # noqa: S310
                    return True
            except urllib.error.URLError:
                return False
        return False
    except urllib.error.URLError:
        return False


def _check_release_assets(version: str) -> bool:
    if not version or not _SAFE_VERSION_PATTERN.match(version):
        return False
    base = (
        f"https://github.com/{PROTON_REPO}/releases/download/GE-Proton{version}/"
        f"GE-Proton{version}"
    )
    archive = f"{base}.tar.gz"
    checksum = f"{base}.sha512sum"
    return _asset_exists(archive) and _asset_exists(checksum)


def _extract_versions(tags: Iterable[str]) -> list[str]:
    versions: list[str] = []
    for tag in tags:
        version = tag.removeprefix("GE-Proton")
        if _SAFE_VERSION_PATTERN.match(version):
            versions.append(version)
    return versions


def find_latest_release_with_assets(skip_version: Optional[str] = None) -> Optional[str]:
    for page in (1, 2, 3):
        url = f"https://api.github.com/repos/{PROTON_REPO}/releases?per_page=10&page={page}"
        payload = _fetch_json(url)
        if not isinstance(payload, list):
            continue
        tags = [item.get("tag_name", "") for item in payload if isinstance(item, dict)]
        for version in _extract_versions(tags):
            if skip_version and version == skip_version:
                continue
            if _check_release_assets(version):
                return version
    return None


def resolve_proton_version(logger: logging.Logger) -> str:
    """Resolve a Proton version and export PROTON_VERSION."""
    configured = (os.environ.get("PROTON_VERSION") or "").strip()
    if configured:
        version = configured
    else:
        version = ""
        payload = _fetch_json(f"https://api.github.com/repos/{PROTON_REPO}/releases/latest")
        detected = ""
        if isinstance(payload, dict):
            tag = str(payload.get("tag_name", ""))
            detected = tag.removeprefix("GE-Proton")
        if detected and _check_release_assets(detected):
            version = detected
            logger.info("Detected latest GE-Proton version: %s", version)
        elif detected:
            logger.info(
                "Latest GE-Proton tag '%s' missing required assets, searching previous releases.",
                detected,
            )
            version = find_latest_release_with_assets(skip_version=detected) or ""
        else:
            version = find_latest_release_with_assets() or ""

    if not version:
        version = FALLBACK_PROTON_VERSION
        logger.info("Falling back to default GE-Proton version: %s", version)

    os.environ["PROTON_VERSION"] = version
    return version


def _download_file(url: str, destination: Path) -> None:
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
        destination.write_bytes(response.read())


def _verify_sha512(archive_path: Path, checksum_path: Path) -> bool:
    checksums = checksum_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    expected = ""
    for line in checksums:
        if archive_path.name in line:
            expected = line.split()[0].strip()
            break
    if not expected:
        return False

    digest = hashlib.sha512()
    with archive_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower() == expected.lower()


def install_proton_if_needed(version: str, logger: logging.Logger) -> str:
    """Install Proton if missing and return installed directory name."""
    proton_dir_name = f"GE-Proton{version}"
    proton_dir = Path(STEAM_COMPAT_DIR) / proton_dir_name
    if proton_dir.exists():
        return proton_dir_name

    logger.info("Installing GE-Proton%s...", version)
    proton_dir.parent.mkdir(parents=True, exist_ok=True)
    base = f"https://github.com/{PROTON_REPO}/releases/download/{proton_dir_name}"
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        archive = tmp / f"{proton_dir_name}.tar.gz"
        checksum = tmp / f"{proton_dir_name}.sha512sum"
        _download_file(f"{base}/{archive.name}", archive)

        checksum_ok = False
        try:
            _download_file(f"{base}/{checksum.name}", checksum)
            checksum_ok = _verify_sha512(archive, checksum)
        except urllib.error.URLError:
            checksum_ok = False

        if not checksum_ok and os.environ.get("PROTON_SKIP_CHECKSUM") != "1":
            raise RuntimeError("Proton checksum verification failed")
        if not checksum_ok:
            logger.warning("Skipping Proton checksum verification (PROTON_SKIP_CHECKSUM=1).")

        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(proton_dir.parent)

    return proton_dir_name


def ensure_proton_compat_data(proton_dir_name: str, logger: logging.Logger) -> None:
    """Create compatdata prefix for ASA app if missing."""
    compat = Path(ASA_COMPAT_DATA)
    if compat.exists():
        return

    logger.info("Preparing Proton compat data directory...")
    source = Path(STEAM_COMPAT_DIR) / proton_dir_name / "files" / "share" / "default_pfx"
    Path(STEAM_COMPAT_DATA).mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, compat)
