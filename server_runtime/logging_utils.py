"""Minimal logging helpers for startup runtime."""

from __future__ import annotations

import logging
import os


def configure_runtime_logging() -> logging.Logger:
    """Configure runtime logger from ASA_LOG_LEVEL."""
    level_name = (os.environ.get("ASA_LOG_LEVEL") or "INFO").upper()
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if level_name in valid_levels:
        level = getattr(logging, level_name)
        invalid_level = None
    else:
        level = logging.INFO
        invalid_level = level_name

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
