"""Central logging configuration utilities for asa_ctrl.

The project deliberately keeps logging lightweight to avoid external deps.
Downstream callers (like the container entrypoint) can call `configure_logging`.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

_LEVEL_MAP = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}


def configure_logging(level: str | int | None = None, *, force: bool = False) -> None:
    """Configure root logger.

    Order of precedence for level:
    1. Explicit `level` argument if given
    2. Environment variable `ASA_LOG_LEVEL`
    3. Fallback to `INFO`
    """
    if level is None:
        level = os.environ.get("ASA_LOG_LEVEL", "INFO")

    if isinstance(level, str):
        level = _LEVEL_MAP.get(level.upper(), logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=force,
    )


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Get a project logger, configuring logging lazily on first access."""
    logger = logging.getLogger(name or "asa_ctrl")
    if not logging.getLogger().handlers:  # pragma: no cover - defensive
        configure_logging()
    return logger


__all__ = ["configure_logging", "get_logger"]
