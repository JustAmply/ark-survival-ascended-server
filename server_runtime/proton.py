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
    IMAGE_VERSION_ENV,  # noqa: F401  (re-exported for callers keyed on the image)
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
# Build metadata that cannot identify a rebuild, so results keyed on it are
# never reused.
UNCACHEABLE_IMAGE_VERSIONS = frozenset({"", "unknown"})

# How a version was arrived at. The origin decides what may happen to it: a
# pinned build is never silently swapped, and a build already fallen back to is
# never re-detected.
ORIGIN_PINNED = "pinned"
ORIGIN_AUTO = "auto"
ORIGIN_FALLBACK = "fallback"


@dataclass(frozen=True)
class ProtonSelection:
    """Which GE-Proton build this container runs, and why.

    Resolution is expensive - it can cost a GitHub round trip, a download and a
    preflight subprocess - and the supervisor relaunches the server in a loop.
    The selection is therefore carried from one launch to the next as a value
    rather than parked in the process environment.
    """

    version: str
    origin: str

    @property
    def directory_name(self) -> str:
        """The install directory `install_proton_if_needed` guarantees."""
        return f"GE-Proton{self.version}"


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


def _pinned_proton_version(settings: RuntimeSettings) -> str:
    """Return the user supplied PROTON_VERSION, when it is usable."""
    configured = (settings.proton_version or "").strip()
    return configured if _SAFE_VERSION_PATTERN.match(configured) else ""


def _export_proton_version(version: str) -> None:
    """Publish the resolved version for anyone inspecting the container.

    Nothing reads this back: resolution is driven by `RuntimeSettings` and the
    `ProtonSelection` the supervisor carries between launches. It is written so
    that `docker exec ... env` still reports the build actually in use.
    """
    os.environ["PROTON_VERSION"] = version


def resolve_proton_version(
    logger: logging.Logger,
    settings: RuntimeSettings,
    previous: Optional[ProtonSelection] = None,
) -> ProtonSelection:
    """Decide which GE-Proton build to run.

    A pinned version always wins. Otherwise an earlier selection is reused as
    is, so the supervisor's relaunch loop neither re-queries GitHub nor retries
    a build that already failed its preflight.
    """
    pinned = _pinned_proton_version(settings)
    if pinned:
        return ProtonSelection(version=pinned, origin=ORIGIN_PINNED)

    if previous is not None:
        logger.debug("Reusing the %s GE-Proton selection %s.", previous.origin, previous.version)
        return previous

    configured = (settings.proton_version or "").strip()
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

    return ProtonSelection(version=version, origin=ORIGIN_AUTO)


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
    settings: RuntimeSettings,
) -> str:
    """Install Proton if missing and return installed directory name."""
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


def _cacheable_image_version(settings: RuntimeSettings) -> str:
    """The image build this container runs, when it can identify a rebuild.

    A preflight verdict only changes when the image's host libraries change, so
    the image version is the cache key. Untagged local builds all report the
    same placeholder, so they are treated as uncacheable rather than sharing a
    stale verdict across rebuilds.
    """
    version = (settings.image_version or "").strip()
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


def find_missing_proton_library(
    proton_dir_name: str, logger: logging.Logger, settings: RuntimeSettings
) -> Optional[str]:
    """Return a shared library GE-Proton needs but this container cannot load.

    The launcher is started without ``STEAM_COMPAT_DATA_PATH`` so it runs all
    module level imports - including the ctypes based Vulkan probe - and then
    exits immediately without touching the wine prefix.

    The verdict depends only on the Proton build and the image's host libraries,
    so it is cached per image version: the supervisor calls this on every
    relaunch and the subprocess would otherwise be paid each time.
    """
    if settings.proton_skip_preflight:
        logger.warning("Skipping Proton preflight check (PROTON_SKIP_PREFLIGHT=1).")
        return None

    script = Path(STEAM_COMPAT_DIR) / proton_dir_name / "proton"
    if not script.is_file():
        return None

    image_version = _cacheable_image_version(settings)
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
    logger: logging.Logger,
    settings: RuntimeSettings,
    previous: Optional[ProtonSelection] = None,
) -> ProtonSelection:
    """Resolve, install and validate Proton; return the usable selection.

    A newly published GE-Proton build may need host libraries this image does
    not ship yet.  Rather than crash-looping on every container start, an
    auto-detected build that fails the preflight is replaced by the known good
    fallback version.  An explicitly pinned ``PROTON_VERSION`` is never
    silently swapped.

    Pass the previous return value back on a relaunch: a selection already
    settled on is reused rather than resolved again.
    """
    selection = resolve_proton_version(logger, settings, previous)
    install_proton_if_needed(selection.version, logger, settings)
    _export_proton_version(selection.version)

    missing = find_missing_proton_library(selection.directory_name, logger, settings)
    if not missing:
        return selection

    logger.error(
        "GE-Proton%s cannot start: shared library '%s' is missing from this container.",
        selection.version,
        missing,
    )
    warn_about_missing_native_libraries(logger)

    if selection.origin == ORIGIN_PINNED:
        raise RuntimeError(
            f"Pinned GE-Proton{selection.version} requires the missing shared library "
            f"'{missing}'. Update the container image or pin a PROTON_VERSION it supports."
        )
    if selection.version == FALLBACK_PROTON_VERSION:
        raise RuntimeError(
            f"Fallback GE-Proton{selection.version} requires the missing shared library "
            f"'{missing}'; the container image needs to be updated."
        )

    logger.warning(
        "Falling back to known good GE-Proton%s; set PROTON_VERSION to override.",
        FALLBACK_PROTON_VERSION,
    )
    fallback = ProtonSelection(version=FALLBACK_PROTON_VERSION, origin=ORIGIN_FALLBACK)
    install_proton_if_needed(fallback.version, logger, settings)
    fallback_missing = find_missing_proton_library(fallback.directory_name, logger, settings)
    if fallback_missing:
        raise RuntimeError(
            f"GE-Proton{selection.version} and fallback GE-Proton{FALLBACK_PROTON_VERSION} both "
            f"require the missing shared library '{fallback_missing}'; the container "
            "image needs to be updated."
        )

    _export_proton_version(fallback.version)
    return fallback
