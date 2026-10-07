"""Exercise real SteamCMD and Proton through FEX, without installing ARK.

Run in a disposable ARM64 image container as gameserver, without existing
volumes or privileged mode. Downloads use the production installers and
checksum verification. A successful test proves the translated launch chain,
not ARK startup, RCON game saving or sustained server operation.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import logging
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
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
    ensure_proton_compat_data,
    prepare_proton,
)
from server_runtime.steamcmd import ensure_steamcmd, probe_steamcmd_translation
from server_runtime.translation import resolve_execution_context, wrap_command
from server_runtime.wine_sync import configure_wine_sync
from verify_translated_lifecycle import verify_translated_lifecycle


MARKER = "ASA_ARM64_PROTON_OK"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--proton-version", default=FALLBACK_PROTON_VERSION,
        help="GE-Proton baseline version, or 'auto' to exercise the default latest-release path.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logger = logging.getLogger("arm64-smoke")
    if (os.getuid(), os.getgid()) != (TARGET_UID, TARGET_GID):
        raise RuntimeError("Run this smoke test as gameserver (25000:25000).")

    settings = replace(
        RuntimeSettings.from_env(),
        proton_version="" if args.proton_version == "auto" else args.proton_version,
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
    logger.info("Verified Proton selection: version=%s, origin=%s", proton.version, proton.origin)
    ensure_proton_compat_data(proton.directory_name, logger)
    environment = LaunchEnvironment.from_process(settings).for_server()
    configure_wine_sync(logger, environment)
    # Proton's Steam shim does not inherit the captured standard handles when
    # creating its Windows child. A fresh file proves execution independently
    # of console attachment and cannot pass from a previous smoke run.
    with tempfile.TemporaryDirectory(prefix="asa-arm64-smoke-") as root:
        marker_file = Path(root) / "result.txt"
        windows_path = "Z:" + str(marker_file).replace("/", "\\")
        params = shlex.join(["/c", f"echo {MARKER}>{windows_path}"])
        command = build_launch_command(proton.directory_name, "cmd.exe", params, context)
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
        if not marker_file.is_file() or marker_file.read_text(encoding="utf-8").strip() != MARKER:
            raise RuntimeError("The Windows command did not create its expected marker through Proton.")
    print("PASS: guest Python, Proton prefix and Windows command execution through FEX.", flush=True)
    verify_translated_lifecycle(proton, context)
    print("ARK was not downloaded or launched; game startup and soak remain unverified.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
