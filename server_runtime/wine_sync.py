"""Wine synchronisation primitives: raise the fd budget, report the mode.

ASA runs several hundred Wine threads, so how Wine implements Windows
synchronisation objects dominates its CPU cost. Modern GE-Proton builds prefer
*fsync* (``futex_waitv``, Linux 5.16+) and fall back to *esync*, which needs one
file descriptor per object. When the descriptor budget is too small Wine
silently drops back to its slow server-side path, so the limit is raised here
and the resulting mode is logged rather than left invisible.
"""

from __future__ import annotations

import logging
import os
import platform
from typing import Optional, Tuple

try:  # pragma: no cover - present on every platform the image runs on
    import resource
except ImportError:  # pragma: no cover - keeps the module importable on Windows
    resource = None  # type: ignore[assignment]

# esync needs roughly one descriptor per synchronisation object; ASA comfortably
# exceeds the 1024 descriptors some daemons still hand out by default.
ESYNC_RECOMMENDED_NOFILE = 524288
FSYNC_MIN_KERNEL = (5, 16)


def raise_file_descriptor_limit(logger: logging.Logger) -> Tuple[int, int]:
    """Raise the soft descriptor limit to the hard limit, returning both."""
    if resource is None:
        return 0, 0
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if soft == hard:
        return soft, hard
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (hard, hard))
    except (OSError, ValueError) as exc:
        logger.debug("Could not raise the open file limit: %s", exc)
        return soft, hard
    logger.info("Raised open file limit from %s to %s for Wine esync.", soft, hard)
    return hard, hard


def kernel_version() -> Optional[Tuple[int, int]]:
    """Return the running kernel's ``(major, minor)``, when it can be parsed."""
    parts = platform.release().split(".")
    try:
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return None


def _disabled(name: str) -> bool:
    return os.environ.get(name) == "1"


def log_sync_mode(logger: logging.Logger, soft_limit: int) -> str:
    """Log which Wine sync backend this container can use, and return its name."""
    version = kernel_version()
    if not _disabled("PROTON_NO_FSYNC") and version is not None and version >= FSYNC_MIN_KERNEL:
        logger.info("Wine synchronisation: fsync (kernel %s.%s).", *version)
        return "fsync"

    if not _disabled("PROTON_NO_ESYNC") and soft_limit >= ESYNC_RECOMMENDED_NOFILE:
        logger.info("Wine synchronisation: esync (%s file descriptors).", soft_limit)
        return "esync"

    logger.warning(
        "Wine synchronisation falls back to the slow server path: fsync needs kernel "
        "%s.%s+ (running %s) and esync needs at least %s file descriptors (have %s). "
        "Raise the container's nofile ulimit to restore esync.",
        *FSYNC_MIN_KERNEL,
        platform.release(),
        ESYNC_RECOMMENDED_NOFILE,
        soft_limit,
    )
    return "server"


def configure_wine_sync(logger: logging.Logger) -> str:
    """Raise the descriptor budget and report the resulting sync backend."""
    soft, _hard = raise_file_descriptor_limit(logger)
    return log_sync_mode(logger, soft)
