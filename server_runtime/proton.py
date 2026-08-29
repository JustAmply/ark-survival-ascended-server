"""GE-Proton resolution and installation helpers."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from .archive_utils import safe_extract_archive
from .constants import (
    ASA_COMPAT_DATA,
    FALLBACK_PROTON_VERSION,
    PROTON_REPO,
    STEAM_COMPAT_DATA,
    STEAM_COMPAT_DIR,
    RuntimeSettings,
)
from .native_libs import warn_about_missing_native_libraries

_SAFE_VERSION_PATTERN = re.compile(r"^[0-9][0-9A-Za-z._-]*$")
_MISSING_LIBRARY_PATTERN = re.compile(
    r"([A-Za-z0-9_.+-]+\.so(?:\.[0-9]+)*): cannot open shared object file"
)
PROTON_PREFLIGHT_TIMEOUT = 60
PROTON_VERSION_SOURCE_ENV = "ASA_PROTON_VERSION_SOURCE"
IMAGE_VERSION_ENV = "ASA_IMAGE_VERSION"
# Build metadata that cannot identify a rebuild, so results keyed on it are
# never reused.
UNCACHEABLE_IMAGE_VERSIONS = frozenset({"", "unknown"})


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


@dataclass(frozen=True)
class ReleaseArchive:
    """Downloadable GE-Proton release assets for one version and architecture."""

    version: str
    asset_base: str
    archive_url: str
    checksum_url: str


def _architecture_suffixes() -> tuple[str, ...]:
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return ("-x86_64",)
    if machine in {"aarch64", "arm64"}:
        return ("-aarch64",)
    return ()


def _asset_bases(version: str) -> list[str]:
    """Candidate asset names, oldest naming scheme first.

    Releases used to ship a single ``GE-ProtonX-Y.tar.gz``; newer ones publish
    per-architecture assets such as ``GE-ProtonX-Y-x86_64.tar.gz``.
    """
    plain = f"GE-Proton{version}"
    return [plain, *(f"{plain}{suffix}" for suffix in _architecture_suffixes())]


def find_release_archive(version: str) -> Optional[ReleaseArchive]:
    """Return the first published asset pair usable on this architecture."""
    if not version or not _SAFE_VERSION_PATTERN.match(version):
        return None
    base = f"https://github.com/{PROTON_REPO}/releases/download/GE-Proton{version}"
    for asset_base in _asset_bases(version):
        archive_url = f"{base}/{asset_base}.tar.gz"
        checksum_url = f"{base}/{asset_base}.sha512sum"
        if _asset_exists(archive_url) and _asset_exists(checksum_url):
            return ReleaseArchive(
                version=version,
                asset_base=asset_base,
                archive_url=archive_url,
                checksum_url=checksum_url,
            )
    return None


def _check_release_assets(version: str) -> bool:
    return find_release_archive(version) is not None


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


def _pinned_proton_version() -> str:
    """Return the user supplied PROTON_VERSION, ignoring values we cached ourselves."""
    if os.environ.get(PROTON_VERSION_SOURCE_ENV) == "auto":
        return ""
    configured = (os.environ.get("PROTON_VERSION") or "").strip()
    return configured if _SAFE_VERSION_PATTERN.match(configured) else ""


def _cached_proton_version() -> str:
    """Return the version an earlier auto-detection in this process settled on."""
    if os.environ.get(PROTON_VERSION_SOURCE_ENV) != "auto":
        return ""
    cached = (os.environ.get("PROTON_VERSION") or "").strip()
    return cached if _SAFE_VERSION_PATTERN.match(cached) else ""


def resolve_proton_version(logger: logging.Logger) -> str:
    """Resolve a Proton version and export PROTON_VERSION."""
    pinned = _pinned_proton_version()
    configured = (os.environ.get("PROTON_VERSION") or "").strip()
    if pinned:
        version = pinned
    elif _cached_proton_version():
        version = _cached_proton_version()
    else:
        if configured:
            logger.warning("Ignoring invalid PROTON_VERSION value: %r", configured)
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
    os.environ[PROTON_VERSION_SOURCE_ENV] = "pinned" if pinned else "auto"
    return version


def _download_file(url: str, destination: Path) -> None:
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
        with destination.open("wb") as handle:
            shutil.copyfileobj(response, handle, length=1024 * 1024)


def _verify_sha512(archive_path: Path, checksum_path: Path) -> bool:
    checksums = checksum_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    expected = ""
    for line in checksums:
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2:
            continue
        checksum_value, checksum_name = parts[0].strip(), parts[1].strip()
        if checksum_name.startswith("*"):
            checksum_name = checksum_name[1:]
        if Path(checksum_name).name == archive_path.name:
            expected = checksum_value
            break
    if not expected:
        return False

    digest = hashlib.sha512()
    with archive_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower() == expected.lower()


def install_proton_if_needed(
    version: str,
    logger: logging.Logger,
    settings: Optional[RuntimeSettings] = None,
) -> str:
    """Install Proton if missing and return installed directory name."""
    settings = settings or RuntimeSettings.from_env()
    proton_dir_name = f"GE-Proton{version}"
    proton_dir = Path(STEAM_COMPAT_DIR) / proton_dir_name
    if proton_dir.exists():
        return proton_dir_name

    release = find_release_archive(version)
    if release is None:
        raise RuntimeError(
            f"No downloadable GE-Proton{version} release assets found for "
            f"architecture '{platform.machine()}'"
        )

    logger.info("Installing GE-Proton%s (asset %s)...", version, release.asset_base)
    proton_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        archive = tmp / f"{release.asset_base}.tar.gz"
        checksum = tmp / f"{release.asset_base}.sha512sum"
        try:
            _download_file(release.archive_url, archive)
        except (urllib.error.URLError, OSError) as exc:
            raise RuntimeError(
                f"Failed to download Proton archive from {release.archive_url}"
            ) from exc

        checksum_ok = False
        try:
            _download_file(release.checksum_url, checksum)
            checksum_ok = _verify_sha512(archive, checksum)
        except urllib.error.URLError:
            checksum_ok = False

        if not checksum_ok and not settings.proton_skip_checksum:
            raise RuntimeError("Proton checksum verification failed")
        if not checksum_ok:
            logger.warning("Skipping Proton checksum verification (PROTON_SKIP_CHECKSUM=1).")

        with tarfile.open(archive, "r:gz") as tar:
            safe_extract_archive(tar, proton_dir.parent)

    _canonicalize_install_dir(proton_dir, release)
    return proton_dir_name


def _canonicalize_install_dir(proton_dir: Path, release: ReleaseArchive) -> None:
    """Give architecture-suffixed archives the canonical GE-ProtonX-Y layout."""
    if proton_dir.is_dir():
        return

    extracted = proton_dir.parent / release.asset_base
    if extracted.is_dir():
        extracted.rename(proton_dir)
        return

    raise RuntimeError(
        f"Proton archive {release.asset_base}.tar.gz did not contain the expected "
        f"'{proton_dir.name}' directory"
    )


def ensure_proton_compat_data(proton_dir_name: str, logger: logging.Logger) -> None:
    """Create compatdata prefix for ASA app if missing."""
    compat = Path(ASA_COMPAT_DATA)
    if compat.exists():
        return

    logger.info("Preparing Proton compat data directory...")
    source = Path(STEAM_COMPAT_DIR) / proton_dir_name / "files" / "share" / "default_pfx"
    Path(STEAM_COMPAT_DATA).mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, compat)


def _preflight_cache_path(proton_dir_name: str) -> Path:
    return Path(STEAM_COMPAT_DIR) / f".preflight-{proton_dir_name}"


def _cacheable_image_version() -> str:
    """The image build this container runs, when it can identify a rebuild.

    A preflight verdict only changes when the image's host libraries change, so
    the image version is the cache key. Untagged local builds all report the
    same placeholder, so they are treated as uncacheable rather than sharing a
    stale verdict across rebuilds.
    """
    version = (os.environ.get(IMAGE_VERSION_ENV) or "").strip()
    return "" if version in UNCACHEABLE_IMAGE_VERSIONS else version


def _read_preflight_cache(
    proton_dir_name: str, image_version: str
) -> Optional[tuple[Optional[str]]]:
    """Return the cached verdict, or ``None`` when this run has to probe again.

    A verdict is itself ``Optional[str]`` - ``None`` means nothing is missing -
    so a hit is wrapped in a one element tuple to stay distinguishable from a
    miss.
    """
    if not image_version:
        return None
    try:
        lines = _preflight_cache_path(proton_dir_name).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    if len(lines) < 2 or lines[0] != image_version:
        return None
    return (lines[1] or None,)


def _write_preflight_cache(
    proton_dir_name: str, image_version: str, missing: Optional[str]
) -> None:
    if not image_version:
        return
    payload = "\n".join([image_version, missing or ""]) + "\n"
    try:
        _preflight_cache_path(proton_dir_name).write_text(payload, encoding="utf-8")
    except OSError:
        # A cache that cannot be written must never block a start.
        pass


def find_missing_proton_library(proton_dir_name: str, logger: logging.Logger) -> Optional[str]:
    """Return a shared library GE-Proton needs but this container cannot load.

    The launcher is started without ``STEAM_COMPAT_DATA_PATH`` so it runs all
    module level imports - including the ctypes based Vulkan probe - and then
    exits immediately without touching the wine prefix.

    The verdict depends only on the Proton build and the image's host libraries,
    so it is cached per image version: the supervisor calls this on every
    relaunch and the subprocess would otherwise be paid each time.
    """
    if os.environ.get("PROTON_SKIP_PREFLIGHT") == "1":
        logger.warning("Skipping Proton preflight check (PROTON_SKIP_PREFLIGHT=1).")
        return None

    script = Path(STEAM_COMPAT_DIR) / proton_dir_name / "proton"
    if not script.is_file():
        return None

    image_version = _cacheable_image_version()
    cached = _read_preflight_cache(proton_dir_name, image_version)
    if cached is not None:
        logger.debug("Reusing cached Proton preflight result for %s.", proton_dir_name)
        return cached[0]

    env = dict(os.environ)
    env.pop("STEAM_COMPAT_DATA_PATH", None)
    try:
        completed = subprocess.run(
            [sys.executable, str(script)],
            env=env,
            capture_output=True,
            text=True,
            timeout=PROTON_PREFLIGHT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        # The preflight must never block a start it cannot judge.
        logger.debug("Proton preflight could not run for %s: %s", proton_dir_name, exc)
        return None

    match = _MISSING_LIBRARY_PATTERN.search(f"{completed.stdout}\n{completed.stderr}")
    missing = match.group(1) if match else None
    _write_preflight_cache(proton_dir_name, image_version, missing)
    return missing


def prepare_proton(
    logger: logging.Logger, settings: Optional[RuntimeSettings] = None
) -> str:
    """Resolve, install and validate Proton; return the usable install directory.

    A newly published GE-Proton build may need host libraries this image does
    not ship yet.  Rather than crash-looping on every container start, an
    auto-detected build that fails the preflight is replaced by the known good
    fallback version.  An explicitly pinned ``PROTON_VERSION`` is never
    silently swapped.
    """
    settings = settings or RuntimeSettings.from_env()
    pinned = _pinned_proton_version()
    version = resolve_proton_version(logger)
    proton_dir_name = install_proton_if_needed(version, logger, settings)

    missing = find_missing_proton_library(proton_dir_name, logger)
    if not missing:
        return proton_dir_name

    logger.error(
        "GE-Proton%s cannot start: shared library '%s' is missing from this container.",
        version,
        missing,
    )
    warn_about_missing_native_libraries(logger)

    if pinned == version:
        raise RuntimeError(
            f"Pinned GE-Proton{version} requires the missing shared library '{missing}'. "
            "Update the container image or pin a PROTON_VERSION it supports."
        )
    if version == FALLBACK_PROTON_VERSION:
        raise RuntimeError(
            f"Fallback GE-Proton{version} requires the missing shared library "
            f"'{missing}'; the container image needs to be updated."
        )

    logger.warning(
        "Falling back to known good GE-Proton%s; set PROTON_VERSION to override.",
        FALLBACK_PROTON_VERSION,
    )
    fallback_dir_name = install_proton_if_needed(
        FALLBACK_PROTON_VERSION, logger, settings
    )
    fallback_missing = find_missing_proton_library(fallback_dir_name, logger)
    if fallback_missing:
        raise RuntimeError(
            f"GE-Proton{version} and fallback GE-Proton{FALLBACK_PROTON_VERSION} both "
            f"require the missing shared library '{fallback_missing}'; the container "
            "image needs to be updated."
        )

    os.environ["PROTON_VERSION"] = FALLBACK_PROTON_VERSION
    return fallback_dir_name
