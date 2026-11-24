"""Read-only runtime status and bounded RCON readiness probe."""

import json
import configparser
import os
from pathlib import Path

from asa_ctrl.common.config import AsaSettings
from asa_ctrl.common.errors import AsaCtrlError
from asa_ctrl.core.rcon import RconClient


def process_alive(pid: int) -> bool:
    # os.kill(pid, 0) terminates the target on Windows; this is a Linux runtime probe.
    if os.name != "posix":
        raise OSError("Runtime process checks require Linux.")
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def server_status(settings: AsaSettings) -> dict:
    path = Path(settings.supervisor_pid_file() or "/home/gameserver/.asa-supervisor.pid")
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
        if not process_alive(pid):
            return {"state": "stopped", "ready": False}
        state = json.loads(path.with_suffix(".status.json").read_text(encoding="utf-8"))
        if not isinstance(state, dict) or state.get("supervisor_pid") != pid:
            return {"state": "unknown", "ready": False}
        if state.get("phase") not in {"starting", "running", "stopping", "stopped", "retrying", "restarting", "failed"}:
            return {"state": "unknown", "ready": False}
        if not isinstance(state.get("failures"), int):
            return {"state": "unknown", "ready": False}
    except (OSError, ValueError, TypeError):
        return {"state": "unknown", "ready": False}
    result = {"state": state["phase"], "ready": False,
              "consecutive_failures": state["failures"]}
    if state["phase"] != "running":
        return result
    try:
        config = settings.rcon_launch_configuration()
        enabled = config.value("RCONEnabled") or settings.get_server_setting("RCONEnabled", "True")
        if enabled.lower() not in {"true", "1", "yes", "on"}:
            result["state"] = "rcon-disabled"
            return result
        port, password = settings.rcon_endpoint(config)
        with RconClient(port=port, password=password, connect_timeout=2,
                        read_timeout=2, retry_count=0, settings=settings) as client:
            client.execute_command("ListPlayers")
    except (AsaCtrlError, OSError, ValueError, configparser.Error):
        result["state"] = "not-ready"
    else:
        result.update(state="ready", ready=True)
    return result
