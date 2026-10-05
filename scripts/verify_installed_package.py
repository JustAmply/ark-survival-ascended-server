"""Smoke-test the installed distribution without importing from the source tree."""

from __future__ import annotations

import importlib
import shutil
import subprocess


REQUIRED_MODULES = (
    "asa_ctrl",
    "asa_ctrl.cli_commands",
    "asa_ctrl.common",
    "asa_ctrl.core",
    "server_runtime",
)


def main() -> None:
    for module_name in REQUIRED_MODULES:
        try:
            importlib.import_module(module_name)
        except ImportError as exc:
            raise SystemExit(
                f"Installed distribution is incomplete: cannot import {module_name!r}: {exc}. "
                "Check [tool.setuptools.packages.find] in pyproject.toml and rebuild the package."
            ) from exc

    executable = shutil.which("asa-ctrl")
    if executable is None:
        raise SystemExit(
            "Installed distribution is incomplete: the 'asa-ctrl' console command is missing. "
            "Check [project.scripts] in pyproject.toml and reinstall the package."
        )

    result = subprocess.run(
        [executable, "--help"],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SystemExit(
            f"Installed 'asa-ctrl --help' failed with exit code {result.returncode}: {detail}"
        )

    print("Installed distribution smoke test passed.")


if __name__ == "__main__":
    main()
