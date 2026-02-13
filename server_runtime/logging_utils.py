"""Minimal logging helpers for startup runtime."""

from __future__ import annotations

import logging
import os


def configure_runtime_logging() -> logging.Logger:
    """Configure runtime logger from ASA_LOG_LEVEL."""
    level_name = (os.environ.get("ASA_LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="[asa-start] %(message)s",
    )
    return logging.getLogger("server_runtime")
