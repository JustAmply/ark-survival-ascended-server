"""Test configuration helpers for a stable temp directory on WSL."""

from __future__ import annotations

import os
import platform
import signal
import tempfile

import pytest


def _is_wsl() -> bool:
    release = platform.release().lower()
    version = platform.version().lower()
    return "microsoft" in release or "microsoft" in version


if _is_wsl() and os.path.isdir("/tmp"):
    os.environ["TMPDIR"] = "/tmp"
    os.environ["TEMP"] = "/tmp"
    os.environ["TMP"] = "/tmp"
    tempfile.tempdir = "/tmp"


@pytest.fixture(autouse=True)
def restore_signal_handlers():
    # Supervisor.run installs process-wide handlers, including on error paths.
    handlers = {
        signum: signal.getsignal(signum)
        for name in ("SIGTERM", "SIGINT", "SIGHUP", "SIGUSR1")
        if (signum := getattr(signal, name, None)) is not None
    }
    yield
    for signum, handler in handlers.items():
        signal.signal(signum, handler)
