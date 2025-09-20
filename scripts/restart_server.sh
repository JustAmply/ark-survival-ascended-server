#!/bin/bash
# Scheduled restart helper for ASA dedicated server.
# Triggered by cron inside the container to request a graceful restart.

set -Eeuo pipefail

PID_FILE="/home/gameserver/.asa-server.pid"
RESTART_FLAG_FILE="/home/gameserver/.asa-restart-requested"
DEFAULT_SAVEWORLD_DELAY=15
DEFAULT_SHUTDOWN_TIMEOUT=180
ASA_CTRL_BIN="/usr/local/bin/asa-ctrl"

log() {
  echo "[asa-restart] $*"
}

broadcast_message() {
  local message="$1"
  if [ -z "$message" ]; then
    return 0
  fi

  # Validate ASA_CTRL_BIN is properly defined and points to a trusted executable
  if [ -z "$ASA_CTRL_BIN" ] || [ ! -f "$ASA_CTRL_BIN" ] || [ ! -x "$ASA_CTRL_BIN" ]; then
    log "Warning: ASA_CTRL_BIN ($ASA_CTRL_BIN) is not a valid executable - skipping broadcast"
    return 1
  fi

  log "Broadcast: $message"
  local quoted
  quoted=$(printf '%q' "$message")
  if ! "$ASA_CTRL_BIN" rcon --exec "ServerChat $quoted" >/dev/null 2>&1; then
    log "Warning: failed to broadcast restart message via RCON."
  fi
}

if [ "${1:-}" = "warn" ]; then
  shift
  broadcast_message "${*:-Server restart imminent.}"
  exit 0
fi

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
    if ! "$ASA_CTRL_BIN" rcon --exec 'saveworld' >/dev/null 2>&1; then
      log "Warning: failed to execute saveworld command via RCON."
    fi
    # Allow the server some time to finish writing the save.
    sleep "$saveworld_delay" || true
  fi

  # Create restart flag to indicate this is a restart, not a shutdown
  log "Creating restart flag to signal restart intent."
  touch "$RESTART_FLAG_FILE" || {
    log "Warning: failed to create restart flag file."
  }

  broadcast_message "Server restarting now."

  log "Sending SIGTERM to server process $pid."
  if ! kill -TERM "$pid" >/dev/null 2>&1; then
    log "Failed to send SIGTERM to $pid."
    rm -f "$RESTART_FLAG_FILE" || true
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

  # Clean up restart flag if it still exists
  rm -f "$RESTART_FLAG_FILE" || true

  log "Restart request completed."
  return 0
}

main "$@"
