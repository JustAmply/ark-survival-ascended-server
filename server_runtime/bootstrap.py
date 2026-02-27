"""Root/bootstrap steps executed before main server supervision."""

from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path


ETC_MACHINE_ID_PATH = "/etc/machine-id"
DBUS_MACHINE_ID_PATH = "/var/lib/dbus/machine-id"


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


def ensure_machine_id(logger: logging.Logger) -> None:
    """Ensure machine-id files exist for components expecting host identity."""
    etc_machine_id = Path(ETC_MACHINE_ID_PATH)
    dbus_machine_id = Path(DBUS_MACHINE_ID_PATH)
    dbus_dir = dbus_machine_id.parent

    machine_id = ""
    try:
        machine_id = etc_machine_id.read_text(encoding="utf-8").strip()
    except OSError:
        machine_id = ""

    if len(machine_id) != 32 or any(c not in "0123456789abcdef" for c in machine_id.lower()):
        machine_id = uuid.uuid4().hex
        try:
            etc_machine_id.parent.mkdir(parents=True, exist_ok=True)
            etc_machine_id.write_text(f"{machine_id}\n", encoding="utf-8")
            logger.info("Initialized /etc/machine-id for container runtime compatibility.")
        except OSError as exc:
            logger.warning("Failed to initialize /etc/machine-id: %s", exc)
            return

    try:
        dbus_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Failed to create %s for machine-id linking: %s", dbus_dir, exc)
        return

    try:
        if dbus_machine_id.exists() or dbus_machine_id.is_symlink():
            dbus_machine_id.unlink()
        dbus_machine_id.symlink_to(etc_machine_id)
    except OSError:
        try:
            dbus_machine_id.write_text(f"{machine_id}\n", encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to provision %s: %s", dbus_machine_id, exc)


def maybe_debug_hold(enable_debug: bool, logger: logging.Logger) -> None:
    """Sleep indefinitely when debug mode is enabled."""
    if not enable_debug:
        return
    logger.info("ENABLE_DEBUG=1 set; entering debug sleep.")
    while True:
        time.sleep(3600)
