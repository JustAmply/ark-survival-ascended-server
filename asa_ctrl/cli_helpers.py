"""Shared CLI helpers for asa-ctrl commands."""

import sys


def exit_with_error(message: str, exit_code: int) -> None:
    """Print an error message and exit with the specified code."""
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(exit_code)
