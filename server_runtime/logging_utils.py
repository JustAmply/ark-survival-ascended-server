"""Minimal logging helpers for startup runtime."""

from __future__ import annotations

import logging
import os


_LEVEL_ALIASES = {
    "WARN": "WARNING",
    "FATAL": "CRITICAL",
}


def configure_runtime_logging() -> logging.Logger:
    """Configure runtime logger from ASA_LOG_LEVEL."""
    configured_level = (os.environ.get("ASA_LOG_LEVEL") or "INFO").upper()
    level_name = _LEVEL_ALIASES.get(configured_level, configured_level)
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if level_name in valid_levels:
        level = getattr(logging, level_name)
        invalid_level = None
    else:
        level = logging.INFO
        invalid_level = configured_level

    logging.basicConfig(
        level=level,
        format="[asa-start] %(message)s",
    )
    logger = logging.getLogger("server_runtime")
    if invalid_level:
        logger.warning(
            "Invalid ASA_LOG_LEVEL %r; falling back to INFO. Valid values: %s.",
            invalid_level,
            ", ".join(sorted(valid_levels)),
        )
    return logger
