"""Native shared libraries the container image must provide for GE-Proton.

GE-Proton loads a few host libraries via ``ctypes`` while its launcher starts,
so a missing package aborts the server before any game code runs.  Declaring
the contract here keeps the image (``Dockerfile``), the CI smoke test and the
runtime preflight in :mod:`server_runtime.proton` in sync.
"""

from __future__ import annotations

import ctypes
import logging
from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class NativeLibrary:
    """A shared library the image must ship, plus why GE-Proton needs it."""

    soname: str
    package: str
    reason: str


REQUIRED_NATIVE_LIBRARIES: tuple[NativeLibrary, ...] = (
    NativeLibrary(
        soname="libvulkan.so.1",
        package="libvulkan1",
        reason="GE-Proton 11+ loads the Vulkan loader while importing its launcher.",
    ),
)


def _is_loadable(soname: str) -> bool:
    try:
        ctypes.CDLL(soname)
    except OSError:
        return False
    return True


def missing_native_libraries(
    libraries: Optional[Iterable[NativeLibrary]] = None,
) -> list[NativeLibrary]:
    """Return the declared libraries that cannot be loaded on this system."""
    candidates = REQUIRED_NATIVE_LIBRARIES if libraries is None else libraries
    return [library for library in candidates if not _is_loadable(library.soname)]


def warn_about_missing_native_libraries(logger: logging.Logger) -> list[NativeLibrary]:
    """Log a remediation hint for every missing library and return them."""
    missing = missing_native_libraries()
    for library in missing:
        logger.warning(
            "Shared library '%s' is missing (Debian package '%s'): %s "
            "Rebuild or update the container image to restore it.",
            library.soname,
            library.package,
            library.reason,
        )
    return missing


def main() -> int:
    """Entry point for image smoke tests: ``python -m server_runtime.native_libs``."""
    missing = missing_native_libraries()
    for library in missing:
        print(f"missing: {library.soname} (install '{library.package}')")
    if missing:
        return 1
    for library in REQUIRED_NATIVE_LIBRARIES:
        print(f"ok: {library.soname}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
