#!/bin/bash
# Refactored ASA server start script – structured & readable
# Responsibilities:
#   1. Ensure permissions & drop privileges
#   2. Optional debug hold
#   3. Install / update steamcmd + server files
#   4. Resolve Proton version & install if missing (AMD64) OR FEX/Wine setup (ARM64)
#   5. Prepare dynamic mods parameter
#   6. Prepare runtime environment (XDG, compat data)
#   7. Handle plugin loader (AsaApi)
#   8. Stream logs
#   9. Launch server via Proton (AMD64) or FEX+Wine (ARM64)

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
ASA_CTRL_BIN="/usr/local/bin/asa-ctrl"
SHUTDOWN_IN_PROGRESS=0
SUPERVISOR_EXIT_REQUESTED=0
RESTART_REQUESTED=0
SUPERVISOR_PID_FILE="/home/gameserver/.asa-supervisor.pid"
RESTART_SCHEDULER_PID=""
GAME_USER_SETTINGS_PATH="$SERVER_FILES_DIR/ShooterGame/Saved/Config/WindowsServer/GameUserSettings.ini"
DEFAULT_START_PARAMS="TheIsland_WP?listen?Port=7777?RCONPort=27020?RCONEnabled=True?ServerAdminPassword=changeme"

# Detect Architecture
ARCH=$(uname -m)

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

has_server_admin_password_in_params() {
  local params="${ASA_START_PARAMS:-}"
  [[ -n "$params" && "$params" == *ServerAdminPassword=* ]]
}

server_admin_password_in_ini() {
  if [ ! -f "$GAME_USER_SETTINGS_PATH" ]; then
    return 1
  fi
  grep -Eq '^[[:space:]]*ServerAdminPassword[[:space:]]*=' "$GAME_USER_SETTINGS_PATH"
}

ensure_server_admin_password() {
  if has_server_admin_password_in_params || server_admin_password_in_ini; then
    return 0
  fi

  if [ -n "${ASA_START_PARAMS:-}" ]; then
    log "ServerAdminPassword missing from start params; appending default fallback"
    log "WARNING: Default ServerAdminPassword=changeme in use; change it via ASA_START_PARAMS or GameUserSettings.ini"
    ASA_START_PARAMS="${ASA_START_PARAMS} -ServerAdminPassword=changeme"
  else
    log "No start params provided; using default map payload with ServerAdminPassword"
    log "WARNING: Default ServerAdminPassword=changeme in use; change it via ASA_START_PARAMS or GameUserSettings.ini"
    ASA_START_PARAMS="$DEFAULT_START_PARAMS"
  fi
  export ASA_START_PARAMS
}

#############################
# 2. Permissions & Privilege Drop
#############################
ensure_permissions() {
  if [ "$(id -u)" != "0" ] || [ -n "${START_SERVER_PRIVS_DROPPED:-}" ]; then
    return 0
  fi
  set -e
  # Check if .fex-emu exists and needs ownership (only if root owns it)
  if [ -d "/home/gameserver/.fex-emu" ]; then
     # Only change if not already correct to avoid massive delay on startup
     if [ "$(stat -c '%u' /home/gameserver/.fex-emu)" != "$TARGET_UID" ]; then
         log "Fixing FEX RootFS ownership (this might take a while)..."
         chown -R "${TARGET_UID}:${TARGET_GID}" "/home/gameserver/.fex-emu" || true
     fi
  fi

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
      chown -R "${TARGET_UID}:${TARGET_GID}" "$d" || true
      touch "$marker" && chown "${TARGET_UID}:${TARGET_GID}" "$marker" || true
    else
      chown "${TARGET_UID}:${TARGET_GID}" "$d" || true
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

  # On ARM64, we must ensure SteamCMD (x86) runs via FEX.
  if [ "$ARCH" = "aarch64" ]; then
    log "ARM64: Running SteamCMD under FEX..."
    # Wrap execution in FEXBash
    # Note: export FEX_ROOTFS inside the subshell/context.
    # RootFS is baked in at this location.
    local cmd="export FEX_ROOTFS=/home/gameserver/.fex-emu/RootFS/Ubuntu_22_04 && cd \"$STEAMCMD_DIR\" && ./steamcmd.sh +force_install_dir \"$SERVER_FILES_DIR\" +login anonymous +app_update 2430930 +@sSteamCmdForcePlatformType windows validate +quit"
    if ! FEXBash -c "$cmd"; then
      log "Failed to update server files via FEX. Check FEX installation and network connectivity."
      exit 1
    fi
  else
    (cd "$STEAMCMD_DIR" && ./steamcmd.sh +force_install_dir "$SERVER_FILES_DIR" +login anonymous +app_update 2430930 validate +quit)
  fi
}

#############################
# 4. Proton Handling (AMD64) / FEX Setup (ARM64)
#############################

# --- AMD64 Proton Logic ---
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
      if [ -z "$version" ] || ! printf '%s' "$version" | grep -Eq '^[0-9][0-9A-Za-z._-]*$'; then
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
  if [ "$ARCH" = "aarch64" ]; then return 0; fi # Skip on ARM

  local detected=""
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
          detected="$ver"
          log "Using detected GE-Proton version: $detected"
        else
          log "Detected tag_name malformed ('$ver'); ignoring"
        fi
      else
        log "Failed to parse latest release tag_name"
      fi
    else
      log "Could not query GitHub API for Proton releases"
    fi
  else
    detected="$PROTON_VERSION"
  fi

  local resolved="${PROTON_VERSION:-}"
  if [ -z "$resolved" ] && [ -n "$detected" ]; then
    if check_proton_release_assets "$detected"; then
      resolved="$detected"
    else
      log "Latest GE-Proton release GE-Proton$detected missing assets; searching previous releases..."
    fi
  fi

  if [ -z "$resolved" ] && [ -z "${PROTON_VERSION:-}" ]; then
    if fallback_ver=$(find_latest_release_with_assets "$detected"); then
      resolved="$fallback_ver"
      log "Using fallback GE-Proton release: $resolved"
    else
      log "No suitable Proton release with assets found via GitHub API"
    fi
  fi

  if [ -z "$resolved" ]; then
    resolved="${PROTON_VERSION:-$FALLBACK_PROTON_VERSION}"
    if [ "$resolved" = "$FALLBACK_PROTON_VERSION" ]; then
      log "Falling back to default Proton version: $resolved"
    fi
  fi

  PROTON_VERSION="$resolved"
  export PROTON_VERSION
  PROTON_DIR_NAME="GE-Proton$PROTON_VERSION"
  PROTON_ARCHIVE_NAME="$PROTON_DIR_NAME.tar.gz"
}

install_proton_if_needed() {
  if [ "$ARCH" = "aarch64" ]; then return 0; fi # Skip on ARM

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
  if [ "$ARCH" = "aarch64" ]; then return 0; fi # Skip on ARM

  if [ ! -d "$ASA_COMPAT_DATA" ]; then
    log "Setting up Proton compat data..."
    mkdir -p "$STEAM_COMPAT_DATA"
    cp -r "$STEAM_COMPAT_DIR/$PROTON_DIR_NAME/files/share/default_pfx" "$ASA_COMPAT_DATA"
  fi
}

# --- ARM64 FEX Logic ---
ensure_fex_setup() {
  if [ "$ARCH" != "aarch64" ]; then return 0; fi

  log "ARM64: Validating FEX environment..."

  # RootFS is baked in. We just verify.
  if [ ! -d "/home/gameserver/.fex-emu/RootFS/Ubuntu_22_04" ]; then
    log "WARNING: FEX RootFS not found at expected location. Was the image built correctly?"
    # Attempt fallback fetch (likely to fail interactively, but logs error)
    if command -v FEXRootFSFetcher >/dev/null; then
         echo "y" | FEXRootFSFetcher || true
    fi
  fi

  # Sync DNS and Hosts from container to FEX RootFS
  # FEX intercepts filesystem calls, hiding the container's /etc/resolv.conf from the emulated process
  log "ARM64: Syncing network configuration to FEX RootFS..."
  # Use absolute path to avoid relying on HOME which might be /root during initialization
  local fex_rootfs_path="/home/gameserver/.fex-emu/RootFS/Ubuntu_22_04"
  cp /etc/resolv.conf "$fex_rootfs_path/etc/resolv.conf" || true
  cp /etc/hosts "$fex_rootfs_path/etc/hosts" || true

  # Check for Wine NLS files (WineHQ Staging usually puts them in /opt/wine-staging/share/wine/nls)
  # We check both standard and opt locations
  if [ ! -d "$fex_rootfs_path/opt/wine-staging/share/wine/nls" ] && [ ! -d "$fex_rootfs_path/usr/share/wine/nls" ]; then
    log "ARM64: Wine NLS files missing in FEX RootFS. This suggests a broken image build."
    # Fallback download logic removed as we now bake WineHQ Staging in.
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
# 5a. Ensure -nosteam
#############################
ensure_nosteam_flag() {
  local params="${ASA_START_PARAMS:-}"
  if printf '%s\n' "$params" | grep -q -- '-nosteam'; then
    return 0
  fi
  if [ -n "$params" ]; then
    params="$params -nosteam"
  else
    params="-nosteam"
  fi
  ASA_START_PARAMS="$params"
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

  # Proton needs these, FEX/Wine might use them too
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

  local runner pass_start_params
  pass_start_params=1

  if [ "$ARCH" = "aarch64" ]; then
     # ARM64 Launch Strategy: FEX + Wine

     log "Launching via FEX-Emu + Wine..."

     export FEX_ROOTFS="/home/gameserver/.fex-emu/RootFS/Ubuntu_22_04"
    local fex_rootfs="$FEX_ROOTFS"
    log "[asa-start] Launching via FEX-Emu + Wine..."
    
    # DEBUG: Find kernel32.dll to verify paths
    log "DEBUG: Searching for kernel32.dll in FEX RootFS..."
    find "$fex_rootfs/opt/wine-staging" -name "kernel32.dll" || log "DEBUG: kernel32.dll not found in /opt/wine-staging"
    find "$fex_rootfs/usr/lib" -name "kernel32.dll" || true

    if command -v FEXBash >/dev/null 2>&1; then
      # FEXBash needs a full command string to execute wine within the emulated environment
      # We rely on standard paths now that Dockerfile copies Wine files to /usr
      # We also explicitly set paths to ensure Wine finds its builtins (kernel32.so)
      runner=(FEXBash -lc '
        export FEX_ROOTFS="$1"
        export LANG=C.UTF-8
        export LC_ALL=C.UTF-8
        export WINEARCH=win64
        export WINEDEBUG=+loaddll
        
        # Explicitly set LD_LIBRARY_PATH and WINEDLLPATH to ensure Wine finds everything
        export LD_LIBRARY_PATH="/usr/lib/wine/x86_64-unix:$LD_LIBRARY_PATH"
        export WINEDLLPATH="/usr/lib/wine/x86_64-unix:/usr/lib/wine/x86_64-windows:/usr/lib/wine/i386-unix:/usr/lib/wine/i386-windows"
        
        # Debug: Verify Wine version
        echo "DEBUG: Checking Wine version:"
        wine --version
        
        shift
        wine "$@"
      ' -- "$fex_rootfs" "$LAUNCH_BINARY_NAME")
    elif command -v FEX >/dev/null 2>&1; then
      runner=(FEX "$FEX_ROOTFS/usr/bin/wine" "$LAUNCH_BINARY_NAME")
    else
      log "FEX not available on ARM64; cannot launch server"
      return 1
     fi

  else
    # AMD64 Launch Strategy: Proton
    if command -v stdbuf >/dev/null 2>&1; then
      runner=(stdbuf -oL -eL "$STEAM_COMPAT_DIR/$PROTON_DIR_NAME/proton" run "$LAUNCH_BINARY_NAME")
    else
      runner=("$STEAM_COMPAT_DIR/$PROTON_DIR_NAME/proton" run "$LAUNCH_BINARY_NAME")
    fi
  fi

  if [ "$pass_start_params" = "1" ]; then
    "${runner[@]}" $ASA_START_PARAMS &
  else
    "${runner[@]}" &
  fi

  local launch_pid=$!
  SERVER_PID="$launch_pid"

  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    log "Server process failed to start correctly"
    return 1
  fi

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

  ensure_permissions

  # Drop privileges happens inside ensure_permissions via re-exec
  # But wait, if we re-exec, the script starts over.
  # ensure_permissions does: exec runuser ... -- /usr/bin/start_server.sh
  # So we need to call ensure_fex_setup *before* ensure_permissions.

  # After re-exec (as user), we continue here (but as user, ensure_permissions returns 0)

  update_server_files
  ensure_server_admin_password

  # Branch here for setup
  resolve_proton_version
  install_proton_if_needed
  ensure_proton_compat_data

  ensure_fex_setup

  inject_mods_param
  ensure_nosteam_flag
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
  ensure_fex_setup
fi
maybe_debug
ensure_permissions
register_supervisor_pid
start_restart_scheduler
ensure_steamcmd
supervisor_loop
exit $?
