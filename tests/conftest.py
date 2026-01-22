"""Test configuration helpers for a stable temp directory on WSL."""

from __future__ import annotations

import os
import platform
import tempfile


def _is_wsl() -> bool:
    release = platform.release().lower()
    version = platform.version().lower()
    return "microsoft" in release or "microsoft" in version


if _is_wsl() and os.path.isdir("/tmp"):
    os.environ["TMPDIR"] = "/tmp"
    os.environ["TEMP"] = "/tmp"
    os.environ["TMP"] = "/tmp"
    tempfile.tempdir = "/tmp"
