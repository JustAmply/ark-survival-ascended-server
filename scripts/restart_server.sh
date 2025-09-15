#!/bin/bash
# Scheduled restart helper for ASA dedicated server.
# Triggered by cron inside the container to request a graceful restart.

set -Eeuo pipefail

PID_FILE="/home/gameserver/.asa-server.pid"
DEFAULT_SAVEWORLD_DELAY=15
DEFAULT_SHUTDOWN_TIMEOUT=180

log() {
  echo "[asa-restart] $*"
}

main() {
  if [ ! -f "$PID_FILE" ]; then
    log "PID file not found at $PID_FILE - server likely not running."
    return 0
  fi

  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -z "$pid" ]; then
    log "PID file empty - skipping restart."
    return 0
  fi

  if ! kill -0 "$pid" >/dev/null 2>&1; then
    log "Process $pid not running - nothing to restart."
    return 0
  fi

  local saveworld_flag saveworld_delay
  saveworld_flag="${ASA_RESTART_SAVEWORLD:-1}"
  saveworld_delay="${ASA_RESTART_SAVEWORLD_DELAY:-$DEFAULT_SAVEWORLD_DELAY}"

  if [ "$saveworld_flag" != "0" ]; then
    log "Issuing saveworld via RCON before restart."
    rcon_err="$({ /usr/local/bin/asa-ctrl rcon --exec 'saveworld' 2>&1 1>/dev/null; } || true)"
    if [ -n "$rcon_err" ]; then
      log "Warning: failed to execute saveworld command via RCON. Possible causes: server not ready, RCON not enabled, or network issue. Error output: $rcon_err"
    fi
    # Allow the server some time to finish writing the save.
    sleep "$saveworld_delay" || true
  fi

  log "Sending SIGTERM to server process $pid."
  if ! kill -TERM "$pid" >/dev/null 2>&1; then
    log "Failed to send SIGTERM to $pid."
    return 1
  fi

  local timeout remaining
  timeout="${ASA_RESTART_SHUTDOWN_TIMEOUT:-$DEFAULT_SHUTDOWN_TIMEOUT}"
  remaining="$timeout"

  while kill -0 "$pid" >/dev/null 2>&1; do
    if [ "$remaining" -le 0 ]; then
      log "Server did not stop within ${timeout}s - forcing termination."
      kill -KILL "$pid" >/dev/null 2>&1 || true
      break
    fi
    sleep 1
    remaining=$((remaining - 1))
  done

  log "Restart request completed."
  return 0
}

main "$@"
