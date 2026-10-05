"""Architecture translation helpers for running x86 binaries on ARM64."""

from __future__ import annotations

import errno
import logging
import os
import platform
import shlex
import shutil
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .constants import (
    DEFAULT_PROTON_PROFILE,
    DEFAULT_TRANSLATOR_MODE,
    DEFAULT_TRANSLATOR_PROBE_TIMEOUT,
    VALID_PROTON_PROFILES,
    VALID_TRANSLATOR_MODES,
    RuntimeSettings,
)


def normalize_architecture(machine: str) -> str:
    """Normalize architecture names to stable identifiers."""
    value = (machine or "").strip().lower()
    if value in {"x86_64", "amd64"}:
        return "amd64"
    if value in {"aarch64", "arm64"}:
        return "arm64"
    return value or "unknown"


@dataclass
class ExecutionContext:
    """Runtime execution context for architecture and translation settings."""

    architecture: str
    translator_mode: str
    runner_prefix: tuple[str, ...]
    wraps_with_shell: bool
    probe_timeout: int
    proton_profile: str
    translator_probe_complete: bool = False

    @property
    def translation_enabled(self) -> bool:
        return self.translator_mode != "none"


def _resolve_translator_mode(raw_mode: str, architecture: str, logger: logging.Logger) -> str:
    mode = (raw_mode or DEFAULT_TRANSLATOR_MODE).strip().lower()
    if mode not in VALID_TRANSLATOR_MODES:
        logger.warning(
            "Invalid ASA_TRANSLATOR_MODE %r; falling back to %r.",
            raw_mode,
            DEFAULT_TRANSLATOR_MODE,
        )
        mode = DEFAULT_TRANSLATOR_MODE

    if mode == "auto":
        return "fex" if architecture == "arm64" else "none"

    if mode == "fex" and architecture != "arm64":
        logger.warning(
            "ASA_TRANSLATOR_MODE=fex on non-ARM64 architecture %r; continuing by request.",
            architecture,
        )
    return mode


def _resolve_probe_timeout(value: int, logger: logging.Logger) -> int:
    if value <= 0:
        logger.warning(
            "Non-positive ASA_TRANSLATOR_PROBE_TIMEOUT %r; using default %s.",
            value,
            DEFAULT_TRANSLATOR_PROBE_TIMEOUT,
        )
        return DEFAULT_TRANSLATOR_PROBE_TIMEOUT
    return value


def _resolve_proton_profile(raw_profile: str, logger: logging.Logger) -> str:
    profile = (raw_profile or DEFAULT_PROTON_PROFILE).strip().lower()
    if profile not in VALID_PROTON_PROFILES:
        logger.warning(
            "Invalid ASA_PROTON_PROFILE %r; falling back to %r.",
            raw_profile,
            DEFAULT_PROTON_PROFILE,
        )
        return DEFAULT_PROTON_PROFILE
    return profile


def _resolve_fex_runner() -> tuple[tuple[str, ...], bool]:
    for candidate in ("FEXBash", "fexbash", "FEX", "FEXInterpreter"):
        binary = shutil.which(candidate)
        if not binary:
            continue
        if candidate in {"FEXBash", "fexbash"}:
            # The pinned FEXBash forwards arguments to the guest /bin/sh.
            return (binary, "-c"), True
        return (binary, "/bin/sh", "-c"), True
    raise RuntimeError(
        "ASA_TRANSLATOR_MODE resolved to 'fex' but no FEX runner was found "
        "(expected one of: FEXBash, fexbash, FEX, FEXInterpreter)."
    )


def resolve_execution_context(
    logger: logging.Logger, settings: RuntimeSettings | None = None
) -> ExecutionContext:
    """Resolve execution context from host architecture and environment."""
    settings = settings or RuntimeSettings.from_env()
    architecture = normalize_architecture(platform.machine())
    mode = _resolve_translator_mode(settings.translator_mode, architecture, logger)
    probe_timeout = _resolve_probe_timeout(settings.translator_probe_timeout, logger)
    proton_profile = _resolve_proton_profile(settings.proton_profile, logger)

    runner_prefix: tuple[str, ...] = ()
    wraps_with_shell = False
    if mode == "fex":
        runner_prefix, wraps_with_shell = _resolve_fex_runner()

    context = ExecutionContext(
        architecture=architecture,
        translator_mode=mode,
        runner_prefix=runner_prefix,
        wraps_with_shell=wraps_with_shell,
        probe_timeout=probe_timeout,
        proton_profile=proton_profile,
    )

    logger.info(
        "Execution context: arch=%s, translator=%s, proton_profile=%s, probe_timeout=%ss",
        context.architecture,
        context.translator_mode,
        context.proton_profile,
        context.probe_timeout,
    )
    return context


def wrap_command(context: ExecutionContext, command: Sequence[str]) -> list[str]:
    """Wrap a command in the configured architecture translator if needed."""
    base = list(command)
    if not base or not base[0]:
        raise ValueError("Command must start with a non-empty executable")

    if not context.translation_enabled:
        return base

    if not context.runner_prefix:
        raise RuntimeError("Translation is enabled but no runner prefix is configured")

    if context.wraps_with_shell:
        return [*context.runner_prefix, "exec " + shlex.join(base)]
    return [*context.runner_prefix, *base]


def format_execution_error(component: str, exc: OSError, context: ExecutionContext) -> str:
    """Create an actionable runtime error message for launch failures."""
    message = str(exc)
    if exc.errno == errno.ENOEXEC or "Exec format error" in message:
        return (
            f"{component} failed with Exec format error. "
            f"Current translator mode is '{context.translator_mode}'. "
            "On ARM64, ensure FEX is installed and ASA_TRANSLATOR_MODE is not 'none'."
        )

    if context.translation_enabled:
        return (
            f"{component} failed while using translator mode '{context.translator_mode}': {message}"
        )
    return f"{component} failed: {message}"


def run_probe_command(
    context: ExecutionContext,
    command: Sequence[str],
    cwd: str | Path,
    logger: logging.Logger,
    probe_name: str,
) -> None:
    """Run a one-time translator probe command for early failure detection."""
    if not context.translation_enabled or context.translator_probe_complete:
        return

    wrapped_command = wrap_command(context, command)
    try:
        with subprocess.Popen(
            wrapped_command,
            cwd=str(cwd),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=os.name == "posix",
        ) as process:
            try:
                _stdout, stderr = process.communicate(timeout=context.probe_timeout)
            except subprocess.TimeoutExpired:
                # SteamCMD's wrapper waits for a child that may still be updating
                # its shared install. Stop the entire probe before retrying it.
                if os.name == "posix":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    process.kill()
                process.communicate()
                raise
            result = subprocess.CompletedProcess(wrapped_command, process.returncode, stderr=stderr)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{probe_name} translation probe timed out after {context.probe_timeout}s. "
            "Increase ASA_TRANSLATOR_PROBE_TIMEOUT if the host is slow."
        ) from exc
    except OSError as exc:
        raise RuntimeError(format_execution_error(f"{probe_name} translation probe", exc, context)) from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        detail = f": {stderr}" if stderr else ""
        raise RuntimeError(
            f"{probe_name} translation probe failed with exit code {result.returncode}{detail}"
        )

    context.translator_probe_complete = True
    logger.info("%s translation probe succeeded.", probe_name)
