#!/bin/bash
# Refactored ASA server start script – structured & readable
# Responsibilities:
#   1. Ensure permissions & drop privileges
#   2. Optional debug hold
#   3. Install / update steamcmd + server files
#   4. Resolve Proton version & install if missing
#   5. Prepare dynamic mods parameter
#   6. Prepare runtime environment (XDG, compat data)
#   7. Handle plugin loader (AsaApi)
#   8. Stream logs
#   9. Launch server via Proton

set -Ee -o pipefail

#############################
# Constants / Paths
#############################
TARGET_UID=25000
TARGET_GID=25000
STEAMCMD_DIR="/home/gameserver/steamcmd"
SERVER_FILES_DIR="/home/gameserver/server-files"
ASA_BINARY_DIR="$SERVER_FILES_DIR/ShooterGame/Binaries/Win64"
LOG_DIR="$SERVER_FILES_DIR/ShooterGame/Saved/Logs"
STEAM_COMPAT_DATA="$SERVER_FILES_DIR/steamapps/compatdata"
ASA_COMPAT_DATA="$STEAM_COMPAT_DATA/2430930"
STEAM_COMPAT_DIR="/home/gameserver/Steam/compatibilitytools.d"
ASA_BINARY_NAME="ArkAscendedServer.exe"
ASA_PLUGIN_BINARY_NAME="AsaApiLoader.exe"
FALLBACK_PROTON_VERSION="8-21"
PID_FILE="/home/gameserver/.asa-server.pid"
RESTART_CRON_FILE="/etc/cron.d/asa-server-restart"
ASA_CTRL_BIN="/usr/local/bin/asa-ctrl"

log() { echo "[asa-start] $*"; }


#############################
# Cron-based scheduled restarts
#############################
setup_restart_cron() {
  if [ "$(id -u)" != "0" ]; then
    return 0
  fi

  rm -f "$RESTART_CRON_FILE"

  local schedule="${SERVER_RESTART_CRON:-}"
  if [ -z "$schedule" ]; then
    return 0
  fi

  log "Configuring scheduled restart (cron): $schedule"
  cat >"$RESTART_CRON_FILE" <<EOF
MAILTO=""
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
$schedule gameserver /usr/bin/restart_server.sh
EOF
  chmod 0644 "$RESTART_CRON_FILE"

  if command -v cron >/dev/null 2>&1; then
    if ! cron; then
      log "Failed to start cron daemon; scheduled restarts disabled."
    fi
  else
    log "Cron binary not found; scheduled restarts disabled."
  fi
}


#############################
# 1. Debug Hold
#############################
maybe_debug() {
  if [ "${ENABLE_DEBUG:-0}" = "1" ]; then
    log "Entering debug mode (sleep)..."
    sleep 999999999
    exit 0
  fi
}

#############################
# 2. Permissions & Privilege Drop
#############################
ensure_permissions() {
  if [ "$(id -u)" != "0" ] || [ -n "${START_SERVER_PRIVS_DROPPED:-}" ]; then
    return 0
  fi
  set -e
  local dirs=(
    "/home/gameserver/Steam"
    "/home/gameserver/steamcmd"
    "$SERVER_FILES_DIR"
    "/home/gameserver/cluster-shared"
  )
  for d in "${dirs[@]}"; do
    mkdir -p "$d"
    local marker="$d/.permissions_set"
    if [ ! -e "$marker" ]; then
      log "Setting ownership for $d to ${TARGET_UID}:${TARGET_GID} (first run)"
      chown -R ${TARGET_UID}:${TARGET_GID} "$d" || true
      touch "$marker" && chown ${TARGET_UID}:${TARGET_GID} "$marker" || true
    else
      chown ${TARGET_UID}:${TARGET_GID} "$d" || true
    fi
  done
  export START_SERVER_PRIVS_DROPPED=1
  if command -v runuser >/dev/null 2>&1; then
    exec runuser -u gameserver -- /usr/bin/start_server.sh
  else
    exec su -s /bin/bash -c "/usr/bin/start_server.sh" gameserver
  fi
}

#############################
# 3. SteamCMD / Server Files
#############################
ensure_steamcmd() {
  if [ ! -d "$STEAMCMD_DIR/linux32" ]; then
    log "Installing steamcmd..."
    mkdir -p "$STEAMCMD_DIR"
    (cd "$STEAMCMD_DIR" && wget -q https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz && tar xf steamcmd_linux.tar.gz)
  fi
}

update_server_files() {
  log "Updating / validating ASA server files..."
  (cd "$STEAMCMD_DIR" && ./steamcmd.sh +force_install_dir "$SERVER_FILES_DIR" +login anonymous +app_update 2430930 validate +quit)
}

#############################
# 4. Proton Handling
#############################
resolve_proton_version() {
  if [ -z "${PROTON_VERSION:-}" ]; then
    log "Detecting latest Proton GE version..."
    if json=$(wget -qO- https://api.github.com/repos/GloriousEggroll/proton-ge-custom/releases/latest 2>/dev/null || true); then
      # Try jq first if present (most reliable)
      if command -v jq >/dev/null 2>&1; then
        ver=$(printf '%s' "$json" | jq -r '.tag_name' 2>/dev/null || true)
      else
        # Fallback to sed extraction of tag_name value
        ver=$(printf '%s' "$json" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\(GE-Proton[^"]*\)".*/\1/p' | head -n1 || true)
      fi
      # Sanitize / normalize: strip optional leading GE-Proton
      if [ -n "${ver:-}" ]; then
        ver=${ver#GE-Proton}
        # Basic validation: must start with a digit and contain only allowed chars (digits, dots, dashes)
        if printf '%s' "$ver" | grep -Eq '^[0-9][0-9A-Za-z._-]*$'; then
          PROTON_VERSION="$ver"
          log "Using detected GE-Proton version: $PROTON_VERSION"
        else
          log "Detected tag_name malformed ('$ver'); ignoring"
        fi
      else
        log "Failed to parse latest release tag_name"
      fi
    else
      log "Could not query GitHub API for Proton releases"
    fi
  fi
  PROTON_VERSION="${PROTON_VERSION:-$FALLBACK_PROTON_VERSION}"
  export PROTON_VERSION
  PROTON_DIR_NAME="GE-Proton$PROTON_VERSION"
  PROTON_ARCHIVE_NAME="$PROTON_DIR_NAME.tar.gz"
}

install_proton_if_needed() {
  if [ -d "$STEAM_COMPAT_DIR/$PROTON_DIR_NAME" ]; then return 0; fi
  log "Downloading Proton $PROTON_DIR_NAME..."
  mkdir -p "$STEAM_COMPAT_DIR"
  local base="https://github.com/GloriousEggroll/proton-ge-custom/releases/download/GE-Proton$PROTON_VERSION"
  local archive="/tmp/$PROTON_ARCHIVE_NAME"
  local sumfile="/tmp/GE-Proton$PROTON_VERSION.sha512sum"
  if ! wget -q -O "$archive" "$base/$PROTON_ARCHIVE_NAME"; then
    echo "Error: failed to download Proton archive."; exit 200
  fi
  log "Verifying checksum..."
  if wget -q -O "$sumfile" "$base/GE-Proton$PROTON_VERSION.sha512sum"; then
    if (cd /tmp && sha512sum -c "$(basename "$sumfile")" 2>/dev/null | grep -q "$PROTON_ARCHIVE_NAME: OK"); then
      log "Checksum OK"
    else
      echo "Error: sha512 checksum verification failed.";
      if [ "${PROTON_SKIP_CHECKSUM:-0}" != "1" ]; then exit 201; else log "Skipping checksum (override)"; fi
    fi
    rm -f "$sumfile" || true
  else
    log "Checksum file unavailable"; [ "${PROTON_SKIP_CHECKSUM:-0}" != "1" ] && exit 201 || log "Continuing without verification"
  fi
  tar -xf "$archive" -C "$STEAM_COMPAT_DIR" && rm -f "$archive"
}

ensure_proton_compat_data() {
  if [ ! -d "$ASA_COMPAT_DATA" ]; then
    log "Setting up Proton compat data..."
    mkdir -p "$STEAM_COMPAT_DATA"
    cp -r "$STEAM_COMPAT_DIR/$PROTON_DIR_NAME/files/share/default_pfx" "$ASA_COMPAT_DATA"
  fi
}

#############################
# 5. Mods parameter
#############################
inject_mods_param() {
  local mods
  mods="$("$ASA_CTRL_BIN" mods-string 2>/dev/null || true)"
  if [ -n "$mods" ]; then
    ASA_START_PARAMS="${ASA_START_PARAMS:-} $mods"
  fi
  export ASA_START_PARAMS
}

#############################
# 6. Runtime Environment (XDG)
#############################
prepare_runtime_env() {
  local uid
  uid="$(id -u)"
  if [ -n "${XDG_RUNTIME_DIR:-}" ]; then
    if [ ! -d "$XDG_RUNTIME_DIR" ] || [ ! -w "$XDG_RUNTIME_DIR" ]; then
      log "XDG_RUNTIME_DIR '$XDG_RUNTIME_DIR' not writable; falling back";
      XDG_RUNTIME_DIR="/tmp/xdg-runtime-$uid"
    fi
  else
    local cand="/run/user/$uid"
    if [ -d "$cand" ] && [ -w "$cand" ]; then
      XDG_RUNTIME_DIR="$cand"
    else
      XDG_RUNTIME_DIR="/tmp/xdg-runtime-$uid"
    fi
  fi
  export XDG_RUNTIME_DIR
  export STEAM_COMPAT_CLIENT_INSTALL_PATH="/home/gameserver/Steam"
  export STEAM_COMPAT_DATA_PATH="$ASA_COMPAT_DATA"
  mkdir -p "$XDG_RUNTIME_DIR" || true
  chmod 700 "$XDG_RUNTIME_DIR" 2>/dev/null || true
}

#############################
# 7. Plugin Loader Handling
#############################
handle_plugin_loader() {
  local archive
  archive=$(basename "$ASA_BINARY_DIR"/AsaApi_*.zip 2>/dev/null || true)
  if [ -f "$ASA_BINARY_DIR/$archive" ]; then
    log "Extracting plugin loader archive $archive"
    (cd "$ASA_BINARY_DIR" && unzip -o "$archive" >/dev/null 2>&1 && rm "$archive")
  fi
  if [ -f "$ASA_BINARY_DIR/$ASA_PLUGIN_BINARY_NAME" ]; then
    LAUNCH_BINARY_NAME="$ASA_PLUGIN_BINARY_NAME"
    log "Plugin loader detected - using $ASA_PLUGIN_BINARY_NAME"
  else
    LAUNCH_BINARY_NAME="$ASA_BINARY_NAME"
  fi
  export LAUNCH_BINARY_NAME
}

#############################
# 8. Log Streaming
#############################
start_log_streamer() {
  mkdir -p "$LOG_DIR"
  local log_file="$LOG_DIR/ShooterGame.log"
  if [ -n "${LOG_STREAMER_PID:-}" ] && kill -0 "$LOG_STREAMER_PID" 2>/dev/null; then
    return 0
  fi

  touch "$log_file"
  # Follow the live log without replaying earlier entries on rotation
  tail -n 0 -F "$log_file" 2>/dev/null &
  LOG_STREAMER_PID=$!
}

#############################
# 9. Launch Server
#############################
launch_server() {
  log "Starting ASA dedicated server..."
  log "Start parameters: $ASA_START_PARAMS"
  cd "$ASA_BINARY_DIR"
  local runner
  if command -v stdbuf >/dev/null 2>&1; then
    runner=(stdbuf -oL -eL "$STEAM_COMPAT_DIR/$PROTON_DIR_NAME/proton" run "$LAUNCH_BINARY_NAME")
  else
    runner=("$STEAM_COMPAT_DIR/$PROTON_DIR_NAME/proton" run "$LAUNCH_BINARY_NAME")
  fi
  "${runner[@]}" $ASA_START_PARAMS &
  SERVER_PID=$!
  echo "$SERVER_PID" > "$PID_FILE"
  wait "$SERVER_PID"
  local exit_code=$?
  log "Server process exited with code $exit_code"
  return $exit_code
}

#############################
# Process Supervision
#############################
handle_shutdown_signal() {
  local signal="$1"
  log "Received signal $signal - initiating graceful shutdown"
  SHUTDOWN_REQUESTED=1
  
  if [ -z "${SERVER_PID:-}" ] || ! kill -0 "$SERVER_PID" 2>/dev/null; then
    log "No server process to shutdown"
    return 0
  fi

  # Graceful shutdown: save world first, then send SIGTERM
  local saveworld_flag saveworld_delay shutdown_timeout
  saveworld_flag="${ASA_SHUTDOWN_SAVEWORLD:-1}"
  saveworld_delay="${ASA_SHUTDOWN_SAVEWORLD_DELAY:-15}"
  shutdown_timeout="${ASA_SHUTDOWN_TIMEOUT:-180}"

  if [ "$saveworld_flag" != "0" ]; then
    log "Issuing saveworld via RCON before shutdown"
    if "$ASA_CTRL_BIN" rcon --exec 'saveworld' >/dev/null 2>&1; then
      log "Saveworld command sent successfully, waiting ${saveworld_delay}s for save completion"
      sleep "$saveworld_delay" || true
    else
      log "Warning: failed to execute saveworld command via RCON"
    fi
  fi

  log "Sending SIGTERM to server process $SERVER_PID"
  kill -TERM "$SERVER_PID" 2>/dev/null || true

  # Wait for graceful shutdown with timeout
  local remaining="$shutdown_timeout"
  local sleep_interval=1
  local max_sleep=5
  while kill -0 "$SERVER_PID" 2>/dev/null; do
    if [ "$remaining" -le 0 ]; then
      log "Server did not stop within ${shutdown_timeout}s - forcing termination"
      kill -KILL "$SERVER_PID" 2>/dev/null || true
      break
    fi
    # Sleep for the smaller of sleep_interval or remaining time
    local this_sleep=$sleep_interval
    if [ "$remaining" -lt "$sleep_interval" ]; then
      this_sleep=$remaining
    fi
    sleep "$this_sleep"
    remaining=$((remaining - this_sleep))
    # Exponential backoff: double sleep_interval up to max_sleep
    if [ "$sleep_interval" -lt "$max_sleep" ]; then
      sleep_interval=$((sleep_interval * 2))
      if [ "$sleep_interval" -gt "$max_sleep" ]; then
        sleep_interval=$max_sleep
      fi
    fi
  done

  log "Graceful shutdown completed"
}

cleanup() {
  if [ -n "${SERVER_PID:-}" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -f "$PID_FILE" || true
  if [ -n "${LOG_STREAMER_PID:-}" ] && kill -0 "$LOG_STREAMER_PID" 2>/dev/null; then
    kill "$LOG_STREAMER_PID" 2>/dev/null || true
  fi
}

run_server_loop() {
  trap 'handle_shutdown_signal TERM' TERM
  trap 'handle_shutdown_signal INT' INT
  trap 'handle_shutdown_signal HUP' HUP
  trap cleanup EXIT

  local base_params
  base_params="${ASA_START_PARAMS:-}"
  local backoff
  backoff="${SERVER_RESTART_BACKOFF:-15}"
  SHUTDOWN_REQUESTED=0

  while true; do
    if [ "${SHUTDOWN_REQUESTED:-0}" = "1" ]; then
      log "Shutdown requested before launch - exiting server loop."
      return 0
    fi

    ASA_START_PARAMS="$base_params"
    export ASA_START_PARAMS

    update_server_files
    resolve_proton_version
    install_proton_if_needed
    ensure_proton_compat_data
    inject_mods_param
    prepare_runtime_env
    handle_plugin_loader
    start_log_streamer

    launch_server
    local exit_code=$?
    rm -f "$PID_FILE" || true
    SERVER_PID=""

    if [ "${SHUTDOWN_REQUESTED:-0}" = "1" ]; then
      log "Shutdown requested - exiting server loop."
      return 0
    fi

    log "Server exited with code $exit_code - restarting in ${backoff}s..."
    sleep "$backoff" || true
  done
}

#############################
# Main Flow
#############################
maybe_debug
setup_restart_cron
ensure_permissions
ensure_steamcmd
run_server_loop
