"""Root/bootstrap steps executed before main server supervision."""

from __future__ import annotations

import logging
import os
import time
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


def maybe_debug_hold(enable_debug: bool, logger: logging.Logger) -> None:
    """Sleep indefinitely when debug mode is enabled."""
    if not enable_debug:
        return
    logger.info("ENABLE_DEBUG=1 set; entering debug sleep.")
    while True:
        time.sleep(3600)
