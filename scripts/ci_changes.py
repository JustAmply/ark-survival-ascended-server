"""Select CI checks from Git changes; uncertainty always selects all checks."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
import os
import re
import subprocess


def required_checks(paths: list[str]) -> tuple[bool, bool]:
    """Return (python, docker), keeping unrecognised inputs on the full path."""
    python = docker = False
    for path in paths:
        if path.startswith(("asa_ctrl/", "server_runtime/")) or path in {
            "Dockerfile", ".dockerignore", "pyproject.toml", "scripts/start_server.sh",
            "scripts/verify_runtime_lifecycle.py",
        }:
            python = docker = True
        elif path.startswith("tests/") or path in {
            "pytest.ini", ".python-version", "uv.lock",
            "scripts/verify_installed_package.py",
        }:
            python = True
        elif PurePosixPath(path).suffix.lower() == ".md" or path.startswith("assets/"):
            continue
        else:
            return True, True
    # An empty diff is ambiguous (for example a release tag); validate it fully.
    return (python, docker) if paths else (True, True)


def changed_paths(base: str) -> list[str]:
    if not re.fullmatch(r"[0-9a-fA-F]{40}", base) or set(base) == {"0"}:
        raise ValueError("No usable base commit")
    result = subprocess.run(
        # Include both sides of renames: moving runtime code into docs must not
        # look like a documentation-only change.
        ["git", "diff", "--no-renames", "--name-only", "-z", base, "HEAD", "--"],
        check=True, capture_output=True,
    )
    return [os.fsdecode(path) for path in result.stdout.split(b"\0") if path]


def main() -> None:
    python = docker = True
    if os.environ.get("CI_EVENT_NAME") != "schedule" and os.environ.get("CI_REF_TYPE") != "tag":
        try:
            python, docker = required_checks(changed_paths(os.environ.get("CI_BASE_SHA", "")))
        except (OSError, ValueError, subprocess.CalledProcessError):
            print("Changed files unavailable; running all checks.")
    outputs = f"python={str(python).lower()}\ndocker={str(docker).lower()}\n"
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(outputs)
    print(outputs, end="")


if __name__ == "__main__":
    main()
