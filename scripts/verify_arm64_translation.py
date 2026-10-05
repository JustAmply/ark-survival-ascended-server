"""Exercise real SteamCMD and Proton through FEX, without installing ARK.

Run in a disposable ARM64 image container as gameserver, without existing
volumes or privileged mode. Downloads use the production installers and
checksum verification. A successful test proves the translated launch chain,
not ARK startup, graceful game shutdown or sustained server operation.
"""

from __future__ import annotations

from dataclasses import replace
import logging
import os
from pathlib import Path
import re
import subprocess
import time

from server_runtime.constants import (
    FALLBACK_PROTON_VERSION,
    STEAMCMD_DIR,
    TARGET_GID,
    TARGET_UID,
    RuntimeSettings,
)
from server_runtime.launch_env import LaunchEnvironment
from server_runtime.proton import (
    build_launch_command,
    build_launch_environment,
    ensure_proton_compat_data,
    prepare_proton,
)
from server_runtime.steamcmd import ensure_steamcmd, probe_steamcmd_translation
from server_runtime.translation import resolve_execution_context, wrap_command
from server_runtime.wine_sync import configure_wine_sync


MARKER = "ASA_ARM64_PROTON_OK"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger = logging.getLogger("arm64-smoke")
    if (os.getuid(), os.getgid()) != (TARGET_UID, TARGET_GID):
        raise RuntimeError("Run this smoke test as gameserver (25000:25000).")

    settings = replace(
        RuntimeSettings.from_env(),
        proton_version=FALLBACK_PROTON_VERSION,
        proton_skip_checksum=False,
        proton_skip_preflight=False,
    )
    context = resolve_execution_context(logger, settings)
    if context.architecture != "arm64" or context.translator_mode != "fex":
        raise RuntimeError("This smoke test requires a native ARM64 host and FEX translation.")

    ensure_steamcmd(logger)
    started = time.monotonic()
    probe_steamcmd_translation(context, logger)
    logger.info("Production SteamCMD probe completed in %.1fs (timeout %ss).",
                time.monotonic() - started, context.probe_timeout)
    steamcmd = subprocess.run(
        wrap_command(context, [str(Path(STEAMCMD_DIR) / "steamcmd.sh"), "+login", "anonymous", "+quit"]),
        cwd=STEAMCMD_DIR,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    steam_output = re.sub(r"\x1b\[[0-9;]*m", "", steamcmd.stdout + steamcmd.stderr)
    print(steam_output, flush=True)
    steamcmd.check_returncode()
    # SteamCMD can exit successfully after a login error; require its final
    # successful anonymous-login status as well as the process exit status.
    if "Waiting for user info...OK" not in steam_output:
        raise RuntimeError("SteamCMD did not confirm successful anonymous login.")
    print("PASS: real SteamCMD self-update and anonymous login through FEX.", flush=True)

    proton = prepare_proton(logger, settings, execution_context=context)
    ensure_proton_compat_data(proton.directory_name, logger)
    environment = build_launch_environment(
        LaunchEnvironment.from_process(settings).for_server(), context.proton_profile
    )
    configure_wine_sync(logger, environment)
    command = build_launch_command(proton.directory_name, "cmd.exe", f"/c echo {MARKER}", context)
    windows = subprocess.run(
        command,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    print(windows.stdout + windows.stderr, flush=True)
    windows.check_returncode()
    if MARKER not in windows.stdout.splitlines():
        raise RuntimeError("The Windows command did not produce its expected output through Proton.")
    print("PASS: guest Python, Proton prefix and Windows command execution through FEX.", flush=True)
    print("ARK was not downloaded or launched; game startup and soak remain unverified.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
