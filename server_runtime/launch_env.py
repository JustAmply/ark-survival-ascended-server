"""The environment the supervisor's child processes are launched with.

The container's own process environment is configuration *input*: it is read
once into `RuntimeSettings` and the launch line, and never written back to.
What each child process receives is assembled here instead, as a value handed
to `subprocess.Popen(env=...)`.

Two children need two different slices, which is what earns this seam:

- the **game server**, launched through Proton, needs the Steam compatibility
  paths, a writable `XDG_RUNTIME_DIR` and headless SDL defaults;
- the **restart scheduler**, which talks to the supervisor through PID files,
  needs those paths and its warning cadence.

Neither slice is a superset of the other, and nothing else in the runtime has
to know which variable belongs to which child.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from .constants import (
    ASA_COMPAT_DATA,
    PID_FILE,
    STEAM_HOME_DIR,
    SUPERVISOR_PID_FILE,
    RuntimeSettings,
)

# Applied with `setdefault` semantics: an operator who supplies their own value
# keeps it, which is what makes running the image on a desktop with a real
# display possible.
HEADLESS_DEFAULTS = {
    "SDL_VIDEODRIVER": "dummy",
    "SDL_AUDIODRIVER": "dummy",
    "XDG_SESSION_TYPE": "headless",
}


def _resolve_runtime_dir(base: Mapping[str, str]) -> str:
    """Return a writable XDG runtime directory, creating it when needed.

    Wine wants somewhere to put its sockets. The configured location is used
    when it is usable, then the systemd-style per-user path, then a temporary
    directory this process owns.
    """
    uid = os.getuid()
    runtime_dir = base.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        path = Path(runtime_dir)
        if not path.is_dir() or not os.access(runtime_dir, os.W_OK):
            runtime_dir = f"/tmp/xdg-runtime-{uid}"
    else:
        candidate = f"/run/user/{uid}"
        if Path(candidate).exists() and os.access(candidate, os.W_OK):
            runtime_dir = candidate
        else:
            runtime_dir = f"/tmp/xdg-runtime-{uid}"

    Path(runtime_dir).mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(runtime_dir, 0o700)
    except OSError:
        pass
    return runtime_dir


@dataclass(frozen=True)
class LaunchEnvironment:
    """Builds the environment for each of the supervisor's child processes."""

    base: Mapping[str, str]
    settings: RuntimeSettings

    @classmethod
    def from_process(
        cls, settings: RuntimeSettings, base: Optional[Mapping[str, str]] = None
    ) -> "LaunchEnvironment":
        """Capture the container's environment as the base for every child."""
        source: Mapping[str, str] = os.environ if base is None else base
        return cls(base=dict(source), settings=settings)

    def for_server(self, launch_line: str = "") -> dict[str, str]:
        """The environment the ASA server runs under Proton with.

        Creates `XDG_RUNTIME_DIR` as a side effect, because the directory has to
        exist before the process that uses it starts.
        """
        env = dict(self.base)
        env["XDG_RUNTIME_DIR"] = _resolve_runtime_dir(self.base)
        env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = STEAM_HOME_DIR
        env["STEAM_COMPAT_DATA_PATH"] = ASA_COMPAT_DATA
        for key, value in HEADLESS_DEFAULTS.items():
            env.setdefault(key, value)
        if launch_line:
            env["ASA_START_PARAMS"] = launch_line
        return env

    def for_scheduler(self) -> dict[str, str]:
        """The environment `asa-ctrl restart-scheduler` runs with.

        The scheduler reads its own configuration from the environment and
        reaches the supervisor only through the PID files named here.
        """
        env = dict(self.base)
        env["SERVER_RESTART_WARNINGS"] = self.settings.restart_warnings_or_default()
        env["ASA_SUPERVISOR_PID_FILE"] = SUPERVISOR_PID_FILE
        env["ASA_SERVER_PID_FILE"] = PID_FILE
        return env
