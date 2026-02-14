"""Root/bootstrap steps executed before main server supervision."""

from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path


def configure_timezone(logger: logging.Logger) -> None:
    """Apply timezone configuration from TZ when possible."""
    tz = (os.environ.get("TZ") or "").strip()
    if not tz:
        logger.info("No TZ provided; using container default timezone.")
        return

    zoneinfo = Path("/usr/share/zoneinfo") / tz
    if not zoneinfo.exists():
        logger.warning("Requested timezone '%s' not found; falling back to UTC.", tz)
        tz = "UTC"
        zoneinfo = Path("/usr/share/zoneinfo") / tz
        if not zoneinfo.exists():
            logger.warning("Timezone data unavailable for '%s'; using environment TZ only.", tz)
            os.environ["TZ"] = tz
            return

    if os.geteuid() != 0:
        os.environ["TZ"] = tz
        logger.info("Not root; cannot update /etc/localtime. Using TZ='%s' only.", tz)
        return

    try:
        localtime = Path("/etc/localtime")
        if localtime.exists() or localtime.is_symlink():
            localtime.unlink()
        localtime.symlink_to(zoneinfo)
    except OSError:
        logger.warning("Failed updating /etc/localtime for '%s'.", tz)

    try:
        Path("/etc/timezone").write_text(f"{tz}\n", encoding="utf-8")
    except OSError:
        logger.warning("Failed writing /etc/timezone for '%s'.", tz)

    os.environ["TZ"] = tz
    logger.info("Configured timezone to '%s'.", tz)


def ensure_machine_id(logger: logging.Logger, path: Path = Path("/etc/machine-id")) -> None:
    """Ensure a machine-id file exists for runtime components that require it."""
    try:
        current_value = path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        current_value = ""

    if current_value:
        return

    if os.geteuid() != 0:
        logger.warning("Machine ID file '%s' is missing/empty and cannot be created without root.", path)
        return

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{uuid.uuid4().hex}\n", encoding="utf-8")
        logger.info("Created machine ID file at '%s'.", path)
    except OSError as exc:
        logger.warning("Failed to create machine ID file '%s': %s", path, exc)


def maybe_debug_hold(enable_debug: bool, logger: logging.Logger) -> None:
    """Sleep indefinitely when debug mode is enabled."""
    if not enable_debug:
        return
    logger.info("ENABLE_DEBUG=1 set; entering debug sleep.")
    while True:
        time.sleep(3600)
