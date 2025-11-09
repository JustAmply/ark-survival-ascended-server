#!/bin/bash
# Refactored ASA server start script – structured & readable
# Responsibilities:
#   1. Ensure permissions & drop privileges
#   2. Optional debug hold
#   3. Download / update ASA server files
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
SERVER_FILES_DIR="/home/gameserver/server-files"
ASA_BINARY_DIR="$SERVER_FILES_DIR/ShooterGame/Binaries/Win64"
LOG_DIR="$SERVER_FILES_DIR/ShooterGame/Saved/Logs"
STEAM_COMPAT_DATA="$SERVER_FILES_DIR/steamapps/compatdata"
ASA_STEAM_APP_ID="${ASA_STEAM_APP_ID:-2430930}"
ASA_COMPAT_DATA="$STEAM_COMPAT_DATA/$ASA_STEAM_APP_ID"
STEAM_COMPAT_DIR="/home/gameserver/Steam/compatibilitytools.d"
ASA_BINARY_NAME="ArkAscendedServer.exe"
ASA_PLUGIN_BINARY_NAME="AsaApiLoader.exe"
FALLBACK_PROTON_VERSION="8-21"
PID_FILE="/home/gameserver/.asa-server.pid"
ASA_CTRL_BIN="/usr/local/bin/asa-ctrl"
DEPOTDOWNLOADER_LINUX_BIN="${DEPOTDOWNLOADER_LINUX_BIN:-/opt/depotdownloader/linux/DepotDownloader}"
DEPOTDOWNLOADER_WINDOWS_BIN="${DEPOTDOWNLOADER_WINDOWS_BIN:-/opt/depotdownloader/windows/DepotDownloader.exe}"
DEPOTDOWNLOADER_COMPAT_DATA="${DEPOTDOWNLOADER_COMPAT_DATA:-$STEAM_COMPAT_DATA/asa-depotdownloader}"
SHUTDOWN_IN_PROGRESS=0
SUPERVISOR_EXIT_REQUESTED=0
RESTART_REQUESTED=0
SUPERVISOR_PID_FILE="/home/gameserver/.asa-supervisor.pid"
RESTART_SCHEDULER_PID=""

log() { echo "[asa-start] $*"; }

register_supervisor_pid() {
  echo "$$" >"$SUPERVISOR_PID_FILE"
}

configure_timezone() {
  local tz zoneinfo
  tz="${TZ:-}"

  if [ -z "$tz" ]; then
    log "No timezone specified via TZ environment variable; using container default."
    return 0
  fi

  zoneinfo="/usr/share/zoneinfo/$tz"
  if [ ! -e "$zoneinfo" ]; then
    log "Requested timezone '$tz' not found - falling back to UTC."
    tz="UTC"
    zoneinfo="/usr/share/zoneinfo/$tz"
    if [ ! -e "$zoneinfo" ]; then
      log "Timezone data for '$tz' unavailable; cannot update /etc/localtime."
      return 0
    fi
  fi

  if [ "$(id -u)" != "0" ]; then
    log "Insufficient permissions to update /etc/localtime; continuing with TZ='$tz'."
    export TZ="$tz"
    return 0
  fi

  local linked=0
  if ln -sf "$zoneinfo" /etc/localtime; then
    linked=1
  else
    log "Failed to update /etc/localtime for timezone '$tz'."
  fi

  if ! printf '%s\n' "$tz" >/etc/timezone 2>/dev/null; then
    log "Failed to write /etc/timezone for '$tz'; continuing."
  fi

  export TZ="$tz"
  if [ "$linked" = "1" ]; then
    log "Configured container timezone to '$tz'."
  else
    log "Using timezone '$tz' via TZ environment variable only."
  fi
}

ensure_machine_id() {
  local target="/etc/machine-id"
  if [ -s "$target" ]; then
    return 0
  fi

  if [ "$(id -u)" != "0" ]; then
    log "Warning: /etc/machine-id missing but insufficient privileges to create it."
    return 0
  fi

  log "Generating /etc/machine-id for Proton compatibility..."
  if command -v dbus-uuidgen >/dev/null 2>&1; then
    if dbus-uuidgen --ensure="$target" >/dev/null 2>&1; then
      chmod 0444 "$target" 2>/dev/null || true
      return 0
    fi
  fi

  if cat /proc/sys/kernel/random/uuid 2>/dev/null | tr -d '-' | tr '[:upper:]' '[:lower:]' | head -c32 >"$target"; then
    chmod 0444 "$target" 2>/dev/null || true
    return 0
  fi

  log "Failed to generate /etc/machine-id"
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
# 3. DepotDownloader / Server Files
#############################
ensure_depotdownloader_linux() {
  if [ -x "$DEPOTDOWNLOADER_LINUX_BIN" ]; then
    return 0
  fi
  log "DepotDownloader Linux binary missing at $DEPOTDOWNLOADER_LINUX_BIN"
  log "This usually means the image was built without downloading the release asset."
  exit 1
}

ensure_depotdownloader_windows() {
  if [ -f "$DEPOTDOWNLOADER_WINDOWS_BIN" ]; then
    return 0
  fi
  log "DepotDownloader Windows binary missing at $DEPOTDOWNLOADER_WINDOWS_BIN"
  log "This usually means the image was built without downloading the release asset."
  exit 1
}

build_depotdownloader_args() {
  local -n __cmd_ref=$1
  __cmd_ref=(-app "$ASA_STEAM_APP_ID" \
    -os windows \
    -osarch 64 \
    -dir "$SERVER_FILES_DIR" \
    -validate)

  if [ -n "${DEPOTDOWNLOADER_MAX_DOWNLOADS:-}" ]; then
    __cmd_ref+=(-max-downloads "$DEPOTDOWNLOADER_MAX_DOWNLOADS")
  fi

  if [ -n "${DEPOTDOWNLOADER_BRANCH:-}" ]; then
    __cmd_ref+=(-branch "$DEPOTDOWNLOADER_BRANCH")
    if [ -n "${DEPOTDOWNLOADER_BRANCH_PASSWORD:-}" ]; then
      __cmd_ref+=(-branchpassword "$DEPOTDOWNLOADER_BRANCH_PASSWORD")
    fi
  fi

  if [ -n "${DEPOTDOWNLOADER_USERNAME:-}" ]; then
    __cmd_ref+=(-username "$DEPOTDOWNLOADER_USERNAME")
    if [ -n "${DEPOTDOWNLOADER_PASSWORD:-}" ]; then
      __cmd_ref+=(-password "$DEPOTDOWNLOADER_PASSWORD")
    fi
  else
    __cmd_ref+=(-anonymous)
  fi

  if [ -n "${DEPOTDOWNLOADER_EXTRA_ARGS:-}" ]; then
    # shellcheck disable=SC2206
    local extra_args=($DEPOTDOWNLOADER_EXTRA_ARGS)
    __cmd_ref+=("${extra_args[@]}")
  fi
}

update_server_files() {
  local args=()
  build_depotdownloader_args args
  "$DEPOTDOWNLOADER_LINUX_BIN" "${args[@]}"
}

ensure_proton_ready() {
  resolve_proton_version
  install_proton_if_needed
}

ensure_companion_compat_data() {
  local target="$1"
  if [ -d "$target" ]; then
    return 0
  fi
  mkdir -p "$(dirname "$target")"
  cp -r "$STEAM_COMPAT_DIR/$PROTON_DIR_NAME/files/share/default_pfx" "$target"
}

run_depotdownloader_windows() {
  ensure_depotdownloader_windows
  ensure_proton_ready
  prepare_runtime_env
  ensure_companion_compat_data "$DEPOTDOWNLOADER_COMPAT_DATA"

  local args=()
  build_depotdownloader_args args
  local proton_bin="$STEAM_COMPAT_DIR/$PROTON_DIR_NAME/proton"
  if [ ! -x "$proton_bin" ]; then
    log "Proton binary missing at $proton_bin"
    return 1
  fi

  local cmd=("$proton_bin" run "$DEPOTDOWNLOADER_WINDOWS_BIN")
  log "Running DepotDownloader (Windows) via Proton..."
  STEAM_COMPAT_CLIENT_INSTALL_PATH="/home/gameserver/Steam" \
  STEAM_COMPAT_DATA_PATH="$DEPOTDOWNLOADER_COMPAT_DATA" \
  "${cmd[@]}" "${args[@]}"
}

maybe_update_server_files() {
  if [ "${ASA_SKIP_STEAM_UPDATE:-0}" = "1" ]; then
    log "Skipping ASA server file update because ASA_SKIP_STEAM_UPDATE=1"
    return 0
  fi

  local linux_rc=0
  local attempted_linux=0

  if [ "${DEPOTDOWNLOADER_FORCE_WINDOWS:-0}" != "1" ]; then
    attempted_linux=1
    log "Updating / validating ASA server files via DepotDownloader (Linux)..."
    ensure_depotdownloader_linux
    if update_server_files; then
      return 0
    else
      linux_rc=$?
    fi
    log "DepotDownloader (Linux) failed with exit code $linux_rc"
  fi

  if [ "${DEPOTDOWNLOADER_DISABLE_WINDOWS_FALLBACK:-0}" = "1" ]; then
    if [ "$attempted_linux" = "1" ]; then
      return "$linux_rc"
    fi
    log "DepotDownloader Windows fallback disabled; aborting update."
    return 1
  fi

  local windows_rc=0
  if run_depotdownloader_windows; then
    return 0
  else
    windows_rc=$?
  fi

  log "DepotDownloader (Windows via Proton) failed with exit code $windows_rc"
  return "$windows_rc"
}

#############################
# 4. Proton Handling
#############################
check_proton_release_assets() {
  local version="$1"
  if [ -z "$version" ]; then return 1; fi
  local base="https://github.com/GloriousEggroll/proton-ge-custom/releases/download/GE-Proton$version"
  local archive_url="$base/GE-Proton$version.tar.gz"
  local sum_url="$base/GE-Proton$version.sha512sum"
  if wget --spider -q "$archive_url" 2>/dev/null && wget --spider -q "$sum_url" 2>/dev/null; then
    return 0
  fi
  return 1
}

find_latest_release_with_assets() {
  local skip_version="${1:-}"
  local page json tags tag version
  for page in 1 2 3; do
    json=$(wget -qO- "https://api.github.com/repos/GloriousEggroll/proton-ge-custom/releases?per_page=10&page=$page" 2>/dev/null || true)
    if [ -z "$json" ]; then
      continue
    fi
    if command -v jq >/dev/null 2>&1; then
      tags=$(printf '%s' "$json" | jq -r '.[].tag_name' 2>/dev/null || true)
    else
      tags=$(printf '%s' "$json" | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\(GE-Proton[^"]*\)".*/\1/p')
    fi
    for tag in $tags; do
      version=${tag#GE-Proton}
      if [ -z "$version" ] || [[ ! "$version" =~ ^[0-9][0-9A-Za-z._-]*$ ]]; then
        continue
      fi
      if [ -n "$skip_version" ] && [ "$version" = "$skip_version" ]; then
        continue
      fi
      if check_proton_release_assets "$version"; then
        printf '%s' "$version"
        return 0
      fi
    done
  done
  return 1
}

resolve_proton_version() {
  local candidates=(
    "10-24" "10-23" "10-21" "10-18" "10-16" "10-13" "10-11" "10-9" "10-8" "10-6"
    "10-2" "9-13" "9-10" "9-5" "9-2" "8-21" "8-16" "8-3" "8-2" "7-41" "7-37"
    "6-9" "6-8" "6-6" "6-2" "6-1" "5-24" "5-21" "5-14"
  )

  if [ -n "${PROTON_VERSION:-}" ]; then
    PROTON_VERSION="${PROTON_VERSION#GE-Proton}"
    log "Using user-specified Proton version: $PROTON_VERSION"
  fi

  if [ -z "${PROTON_VERSION:-}" ]; then
    log "Selecting Proton version from built-in list..."
    for candidate in "${candidates[@]}"; do
      if check_proton_release_assets "$candidate"; then
        PROTON_VERSION="$candidate"
        log "Selected GE-Proton$PROTON_VERSION"
        break
      fi
    done
  fi

  if [ -z "${PROTON_VERSION:-}" ]; then
    PROTON_VERSION="$FALLBACK_PROTON_VERSION"
    log "No listed release available; falling back to GE-Proton$PROTON_VERSION"
  fi

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
    if (cd /tmp && sha512sum -c "$(basename "$sumfile")" >/tmp/proton_sha_check 2>&1); then
      log "Checksum OK"
    else
      echo "Error: sha512 checksum verification failed."
      cat /tmp/proton_sha_check >&2 || true
      if [ "${PROTON_SKIP_CHECKSUM:-0}" != "1" ]; then exit 201; else log "Skipping checksum (override)"; fi
    fi
    rm -f /tmp/proton_sha_check || true
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

ensure_server_binary_exists() {
  if [ ! -d "$ASA_BINARY_DIR" ]; then
    log "ASA binary directory '$ASA_BINARY_DIR' missing after update."
    return 1
  fi
  if [ ! -f "$ASA_BINARY_DIR/$ASA_BINARY_NAME" ]; then
    log "ASA server binary '$ASA_BINARY_NAME' not found in $ASA_BINARY_DIR."
    return 1
  fi
  return 0
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
perform_shutdown_sequence() {
  local signal="$1" purpose="$2"
  if [ "${SHUTDOWN_IN_PROGRESS:-0}" = "1" ]; then
    log "Signal $signal received but shutdown already in progress"
    return 0
  fi
  SHUTDOWN_IN_PROGRESS=1
  log "Received signal $signal for $purpose - saving world and stopping server"

  if [ -z "${SERVER_PID:-}" ] || ! kill -0 "$SERVER_PID" 2>/dev/null; then
    if [ -z "${SERVER_PID:-}" ]; then
      log "Shutdown requested before server launch - nothing to do"
    else
      log "Server process already stopped"
    fi
    return 0
  fi

  local saveworld_delay shutdown_timeout
  saveworld_delay="${ASA_SHUTDOWN_SAVEWORLD_DELAY:-15}"
  shutdown_timeout="${ASA_SHUTDOWN_TIMEOUT:-180}"

  log "Issuing saveworld via RCON before shutdown"
  if "$ASA_CTRL_BIN" rcon --exec 'saveworld' >/dev/null 2>&1; then
    log "Saveworld command sent successfully, waiting ${saveworld_delay}s for save completion"
    sleep "$saveworld_delay" || true
  else
    log "Warning: failed to execute saveworld command via RCON"
  fi

  log "Sending SIGTERM to server process $SERVER_PID"
  kill -TERM "$SERVER_PID" 2>/dev/null || true

  local elapsed=0
  while kill -0 "$SERVER_PID" 2>/dev/null && [ "$elapsed" -lt "$shutdown_timeout" ]; do
    sleep 1
    elapsed=$((elapsed + 1))
  done

  if kill -0 "$SERVER_PID" 2>/dev/null; then
    log "Server did not stop within ${shutdown_timeout}s - forcing termination"
    kill -KILL "$SERVER_PID" 2>/dev/null || true
  else
    log "Server process stopped cleanly"
  fi
}

handle_shutdown_signal() {
  local signal="$1"
  SUPERVISOR_EXIT_REQUESTED=1
  perform_shutdown_sequence "$signal" "container shutdown"
}

handle_restart_signal() {
  local signal="$1"
  RESTART_REQUESTED=1
  perform_shutdown_sequence "$signal" "scheduled restart"
}

start_restart_scheduler() {
  local cron_expression
  cron_expression="${SERVER_RESTART_CRON:-}"
  if [ -z "$cron_expression" ]; then
    return 0
  fi

  if [ ! -x "$ASA_CTRL_BIN" ]; then
    log "Restart scheduler requested but asa-ctrl CLI missing; skipping"
    return 0
  fi

  if [ -n "${RESTART_SCHEDULER_PID:-}" ] && kill -0 "$RESTART_SCHEDULER_PID" 2>/dev/null; then
    return 0
  fi

  export SERVER_RESTART_CRON
  export SERVER_RESTART_WARNINGS="${SERVER_RESTART_WARNINGS:-30,5,1}"
  export ASA_SUPERVISOR_PID_FILE="$SUPERVISOR_PID_FILE"
  export ASA_SERVER_PID_FILE="$PID_FILE"

  "$ASA_CTRL_BIN" restart-scheduler &
  RESTART_SCHEDULER_PID=$!
  log "Started restart scheduler (PID $RESTART_SCHEDULER_PID) with cron '$SERVER_RESTART_CRON'"
}

cleanup() {
  if [ -n "${SERVER_PID:-}" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -f "$PID_FILE" || true
  rm -f "$SUPERVISOR_PID_FILE" || true
  if [ -n "${LOG_STREAMER_PID:-}" ] && kill -0 "$LOG_STREAMER_PID" 2>/dev/null; then
    kill "$LOG_STREAMER_PID" 2>/dev/null || true
  fi
  if [ -n "${RESTART_SCHEDULER_PID:-}" ] && kill -0 "$RESTART_SCHEDULER_PID" 2>/dev/null; then
    kill "$RESTART_SCHEDULER_PID" 2>/dev/null || true
    wait "$RESTART_SCHEDULER_PID" 2>/dev/null || true
  fi
}

supervisor_loop() {
  local exit_code restart_delay
  restart_delay="${SERVER_RESTART_DELAY:-15}"

  while true; do
    run_server
    exit_code=$?

    if [ "${SUPERVISOR_EXIT_REQUESTED:-0}" = "1" ]; then
      log "Supervisor exit requested - stopping with code $exit_code"
      return "$exit_code"
    fi

    if [ "${RESTART_REQUESTED:-0}" = "1" ]; then
      log "Scheduled restart completed - relaunching server after ${restart_delay}s"
    else
      log "Server exited unexpectedly with code $exit_code - restarting after ${restart_delay}s"
    fi

    RESTART_REQUESTED=0
    SHUTDOWN_IN_PROGRESS=0

    sleep "$restart_delay" || true
  done
}

run_server() {
  trap 'handle_shutdown_signal TERM' TERM
  trap 'handle_shutdown_signal INT' INT
  trap 'handle_shutdown_signal HUP' HUP
  trap 'handle_restart_signal USR1' USR1
  trap cleanup EXIT

  resolve_proton_version
  install_proton_if_needed
  ensure_proton_compat_data
  maybe_update_server_files
  if ! ensure_server_binary_exists; then
    log "Server files missing - aborting startup"
    exit 202
  fi
  inject_mods_param
  prepare_runtime_env
  handle_plugin_loader
  start_log_streamer

  launch_server
  local exit_code=$?
  rm -f "$PID_FILE" || true
  SERVER_PID=""
  return $exit_code
}

#############################
# Main Flow
#############################
if [ "$(id -u)" = "0" ]; then
  configure_timezone
  ensure_machine_id
fi
maybe_debug
ensure_permissions
register_supervisor_pid
start_restart_scheduler
supervisor_loop
exit $?
