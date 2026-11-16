"""Smoke-test the installed distribution without importing from the source tree."""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys


REQUIRED_MODULES = (
    "asa_ctrl",
    "asa_ctrl.cli_commands",
    "asa_ctrl.common",
    "asa_ctrl.core",
    "asa_ctrl.core.status",
    "asa_ctrl.core.diagnostics",
    "server_runtime",
)


def main() -> None:
    if sys.version_info[:2] != (3, 15):
        raise SystemExit("Installed distribution must be verified with Python 3.15.")

    for module_name in REQUIRED_MODULES:
        try:
            importlib.import_module(module_name)
        except ImportError as exc:
            raise SystemExit(
                f"Installed distribution is incomplete: cannot import {module_name!r}: {exc}. "
                "Check pyproject.toml build configuration and rebuild the package."
            ) from exc

    executable = shutil.which("asa-ctrl")
    if executable is None:
        raise SystemExit(
            "Installed distribution is incomplete: the 'asa-ctrl' console command is missing. "
            "Check [project.scripts] in pyproject.toml and reinstall the package."
        )

    for command in ([], ["status"], ["config", "check"], ["doctor"]):
        arguments = [executable, *command, "--help"]
        result = subprocess.run(
            arguments,
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise SystemExit(
                f"Installed {' '.join(arguments[1:])!r} failed with exit code {result.returncode}: {detail}"
            )

    print("Installed distribution smoke test passed.")


if __name__ == "__main__":
    main()
