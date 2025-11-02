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
ASA_CTRL_BIN="/usr/local/bin/asa-ctrl"
SHUTDOWN_IN_PROGRESS=0
SUPERVISOR_EXIT_REQUESTED=0
RESTART_REQUESTED=0
SUPERVISOR_PID_FILE="/home/gameserver/.asa-supervisor.pid"
RESTART_SCHEDULER_PID=""

log() { echo "[asa-start] $*"; }

#############################
# Architecture Detection
#############################
detect_architecture() {
  local arch
  arch="$(uname -m)"
  case "$arch" in
    x86_64|amd64)
      ARCH="amd64"
      USE_BOX64=0
      ;;
    aarch64|arm64)
      ARCH="arm64"
      USE_BOX64=1
      log "ARM64 architecture detected - using Box64 for x86_64 emulation"
      ;;
    *)
      log "Warning: Unsupported architecture: $arch. Falling back to amd64 mode which may not work correctly on this platform."
      ARCH="amd64"
      USE_BOX64=0
      ;;
  esac
  export ARCH USE_BOX64
}

configure_box64() {
  if [ "$USE_BOX64" != "1" ]; then
    return 0
  fi

  # Box64 environment configuration for optimal performance
  export BOX64_NOBANNER=1
  export BOX64_LOG=0
  export BOX64_SHOWSEGV=0
  export BOX64_DYNAREC_BIGBLOCK=3
  export BOX64_DYNAREC_STRONGMEM=1
  export BOX64_DYNAREC_FASTNAN=1
  export BOX64_DYNAREC_FASTROUND=1
  export BOX64_DYNAREC_SAFEFLAGS=0
  export BOX64_DYNAREC_CALLRET=1
  export BOX64_DYNAREC_X87DOUBLE=1

  log "Box64 environment configured for performance"
}

configure_box86_runtime() {
  if [ "$USE_BOX64" != "1" ]; then
    return 0
  fi

  # Build the Box86 search paths dynamically so we only include
  # directories that actually exist in the current container.
  local -a ld_paths=(
    "$STEAMCMD_DIR/linux32"
    "/usr/lib/box86-i386-linux-gnu"
    "/usr/lib/i386-linux-gnu"
    "/lib/i386-linux-gnu"
  )
  local -a exec_paths=(
    "$STEAMCMD_DIR"
    "$STEAMCMD_DIR/linux32"
    "/usr/lib/box86-i386-linux-gnu"
  )

  local -a filtered_ld_paths=()
  local path
  for path in "${ld_paths[@]}"; do
    if [ -d "$path" ]; then
      filtered_ld_paths+=("$path")
    fi
  done

  if [ ${#filtered_ld_paths[@]} -gt 0 ]; then
    local joined_ld_path
    joined_ld_path=$(IFS=:; echo "${filtered_ld_paths[*]}")
    export BOX86_LD_LIBRARY_PATH="$joined_ld_path"
  fi

  local -a filtered_exec_paths=()
  for path in "${exec_paths[@]}"; do
    if [ -d "$path" ]; then
      filtered_exec_paths+=("$path")
    fi
  done

  if [ ${#filtered_exec_paths[@]} -gt 0 ]; then
    local joined_exec_path
    joined_exec_path=$(IFS=:; echo "${filtered_exec_paths[*]}")
    export BOX86_PATH="$joined_exec_path"
  fi

  if [ -n "${BOX86_LD_LIBRARY_PATH:-}" ]; then
    log "Configured Box86 LD_LIBRARY_PATH=$BOX86_LD_LIBRARY_PATH"
  else
    log "Warning: No Box86 library paths detected; steamcmd may fail. Ensure Box86 is installed and library directories exist."
  fi
}

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

  configure_box86_runtime
}

update_server_files() {
  log "Updating / validating ASA server files..."
  local -a steamcmd_cmd=("./steamcmd.sh")
  local -a steamcmd_env=()

  if [ "$USE_BOX64" = "1" ]; then
    # steamcmd provides a 32-bit ELF which needs box86 rather than box64.
    # Instead of executing the shell script via box86 (which triggers an ELF
    # header error) we instruct the bootstrap script to launch the 32-bit
    # binary through box86 by setting the DEBUGGER variable it honours.
    if command -v box86 >/dev/null 2>&1; then
      log "Routing steamcmd through box86 debugger wrapper"
      steamcmd_env+=("DEBUGGER=box86")
    else
      log "Warning: Box86 not found; attempting to use qemu-i386 for steamcmd."
      if command -v qemu-i386 >/dev/null 2>&1; then
        steamcmd_env+=("DEBUGGER=qemu-i386")
      else
        log "Error: No compatible x86 emulator available; aborting steamcmd update"
        return 1
      fi
    fi
  fi

  (
    cd "$STEAMCMD_DIR"
    env "${steamcmd_env[@]}" \
      "${steamcmd_cmd[@]}" \
      +force_install_dir "$SERVER_FILES_DIR" \
      +login anonymous \
      +app_update 2430930 validate \
      +quit
  )
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
  local prefix_dir="$ASA_COMPAT_DATA"
  local default_prefix="$STEAM_COMPAT_DIR/$PROTON_DIR_NAME/files/share/default_pfx"
  local prefix_version_file="$prefix_dir/version"
  local default_version_file="$default_prefix/version"
  local expected_version=""
  local current_version=""
  local preserve_prefix="${ASA_PRESERVE_PREFIX:-0}"

  if [ -f "$default_version_file" ]; then
    expected_version="$(head -n1 "$default_version_file" 2>/dev/null | tr -d '\r')"
  fi
  if [ -z "$expected_version" ]; then
    expected_version="$PROTON_DIR_NAME"
  fi

  if [ -f "$prefix_version_file" ]; then
    current_version="$(head -n1 "$prefix_version_file" 2>/dev/null | tr -d '\r')"
  fi

  if [ -d "$prefix_dir" ]; then
    if [ -z "$current_version" ] || [ "$current_version" != "$expected_version" ]; then
      log "Detected Proton prefix version mismatch (have: '${current_version:-unknown}', expected: '$expected_version')."
      if [ "$preserve_prefix" = "1" ]; then
        log "ASA_PRESERVE_PREFIX=1 set; preserving existing prefix despite mismatch."
        return 0
      fi

      local backup_dir="${prefix_dir}.bak.$(date +%Y%m%d%H%M%S)"
      if mv "$prefix_dir" "$backup_dir" 2>/dev/null; then
        log "Backed up mismatched prefix to $backup_dir"
      else
        log "Failed to back up mismatched prefix; purging $prefix_dir"
        rm -rf "$prefix_dir"
      fi
    fi
  fi

  if [ ! -d "$prefix_dir" ]; then
    log "Setting up Proton compat data from $default_prefix"
    mkdir -p "$STEAM_COMPAT_DATA"
    if [ ! -d "$default_prefix" ]; then
      log "Error: Default Proton prefix not found at $default_prefix"
      return 1
    fi
    # Use 'cp -a' to preserve symlinks, permissions, and timestamps when copying the Proton prefix.
    # This is important for correct operation; Ubuntu 24.04 base image guarantees support for '-a'.
    if ! cp -a "$default_prefix" "$prefix_dir"; then
      log "Error: Failed to copy default Proton prefix to $prefix_dir"
      rm -rf "$prefix_dir"
      return 1
    fi
  fi

  return 0
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
# 8b. Machine ID Preparation
#############################
ensure_machine_id() {
  local target="/etc/machine-id"

  if [ -s "$target" ]; then
    return 0
  fi

  log "machine-id missing - attempting to create $target"

  if [ "$(id -u)" != "0" ]; then
    log "Warning: Unable to create $target without root privileges"
    return 1
  fi

  local source="/var/lib/dbus/machine-id"
  if [ -r "$source" ] && [ -s "$source" ]; then
    if cp "$source" "$target" 2>/dev/null; then
      log "Copied machine-id from $source"
      return 0
    fi
  fi

  if command -v dbus-uuidgen >/dev/null 2>&1; then
    if dbus-uuidgen --ensure="$target" >/dev/null 2>&1; then
      log "Generated machine-id via dbus-uuidgen"
      return 0
    fi
  fi

  local new_id=""
  if command -v uuidgen >/dev/null 2>&1; then
    new_id=$(uuidgen 2>/dev/null || true)
  elif [ -r /proc/sys/kernel/random/uuid ]; then
    new_id=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || true)
  fi

  if [ -n "$new_id" ]; then
    # machine-id format requires 32 hex digits without hyphens
    new_id=${new_id//-/}
    if printf '%s\n' "$new_id" >"$target" 2>/dev/null; then
      log "Generated machine-id from random UUID fallback"
      return 0
    fi
  fi

  log "Warning: Unable to create $target - Proton may fail to start"
  return 1
}

#############################
# 9. Launch Server
#############################
launch_server() {
  log "Starting ASA dedicated server..."
  log "Start parameters: $ASA_START_PARAMS"
  cd "$ASA_BINARY_DIR"
  local -a runner
  local proton_path="$STEAM_COMPAT_DIR/$PROTON_DIR_NAME/proton"

  # Detect whether the Proton launcher is an ELF binary or a text script
  # without relying on external tools like 'file' (not installed in image).
  local proton_is_text_script=1
  if [ -f "$proton_path" ]; then
    # Read first 4 bytes and compare to ELF magic 0x7F 45 4C 46
    local magic
    magic=$(od -An -tx1 -N4 "$proton_path" 2>/dev/null | tr -d ' \n' || true)
    # ELF magic: 0x7F 'E' 'L' 'F'
    if [ "$magic" = "7f454c46" ]; then
      proton_is_text_script=0
    fi
  fi

  if [ "$USE_BOX64" = "1" ]; then
    export PROTON_USE_WINED3D=0
    # Box64 already normalizes stdout/stderr buffering; piping through stdbuf can
    # introduce hangs or dropped output, so we skip stdbuf for emulated runs.
    if [ "$proton_is_text_script" = "1" ]; then
      log "Detected Proton launcher script - executing via python3 for Box64 compatibility"
      runner=(python3 "$proton_path" run "$LAUNCH_BINARY_NAME")
    else
      # ARM64 fallback: Use Box64 to run Proton binary directly
      runner=(box64 "$proton_path" run "$LAUNCH_BINARY_NAME")
    fi
  else
    # AMD64: Direct execution
    if command -v stdbuf >/dev/null 2>&1; then
      runner=(stdbuf -oL -eL "$proton_path" run "$LAUNCH_BINARY_NAME")
    else
      runner=("$proton_path" run "$LAUNCH_BINARY_NAME")
    fi
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

  if [ ! -x "$ASA_CTRL_BIN" ]; then
    log "asa-ctrl CLI missing at $ASA_CTRL_BIN; skipping pre-shutdown saveworld"
  else
    log "Issuing saveworld via RCON before shutdown"
    local rcon_output="" rcon_status=0 reason=""
    if rcon_output="$("$ASA_CTRL_BIN" rcon --exec 'saveworld' 2>&1)"; then
      log "Saveworld command sent successfully, waiting ${saveworld_delay}s for save completion"
      if [ -n "$rcon_output" ]; then
        while IFS= read -r line; do
          [ -n "$line" ] && log "RCON response: $line"
        done <<<"$rcon_output"
      fi
      sleep "$saveworld_delay" || true
    else
      rcon_status=$?
      case "$rcon_status" in
        3)
          reason="RCON password not found; configure ServerAdminPassword in start params or GameUserSettings.ini."
          ;;
        4)
          reason="RCON authentication failed; verify ServerAdminPassword matches the server configuration."
          ;;
        6)
          reason="RCON connection failed; ensure RCONPort is reachable and RCONEnabled=True."
          ;;
        8)
          reason="RCON request timed out; the server may be busy or shutting down."
          ;;
        *)
          reason="exit code $rcon_status"
          ;;
      esac
      log "Warning: failed to execute saveworld command via RCON (${reason})"
      if [ -n "$rcon_output" ]; then
        while IFS= read -r line; do
          [ -n "$line" ] && log "RCON output: $line"
        done <<<"$rcon_output"
      fi
    fi
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

  update_server_files
  resolve_proton_version
  install_proton_if_needed
  ensure_proton_compat_data || return 1
  if [ ! -d "$ASA_COMPAT_DATA" ]; then
    log "Error: Proton compat data missing at $ASA_COMPAT_DATA"
    return 1
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
detect_architecture
configure_box64
if [ "$(id -u)" = "0" ]; then
  configure_timezone
fi
ensure_machine_id || true
maybe_debug
ensure_permissions
register_supervisor_pid
start_restart_scheduler
ensure_steamcmd
supervisor_loop
exit $?
