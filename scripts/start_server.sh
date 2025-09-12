#!/bin/bash

# Safer shell defaults (no -u because we reference optional env vars)
set -Ee -o pipefail

# If running as root, fix volume permissions once, then drop to 'gameserver'.
if [ "$(id -u)" = "0" ] && [ -z "${START_SERVER_PRIVS_DROPPED:-}" ]; then
  set -e

  TARGET_UID=25000
  TARGET_GID=25000
  DIRS=(
    "/home/gameserver/Steam"
    "/home/gameserver/steamcmd"
    "/home/gameserver/server-files"
    "/home/gameserver/cluster-shared"
  )

  for d in "${DIRS[@]}"; do
    mkdir -p "$d"
    # Only run recursive chown once per volume using a marker file to avoid slow startups.
    MARKER="$d/.permissions_set"
    if [ ! -e "$MARKER" ]; then
      echo "Setting ownership for $d to ${TARGET_UID}:${TARGET_GID} (first run)"
      chown -R ${TARGET_UID}:${TARGET_GID} "$d" || true
      # Create marker owned by target user to skip on subsequent starts
      touch "$MARKER"
      chown ${TARGET_UID}:${TARGET_GID} "$MARKER" || true
    else
      # Ensure the root directory has correct ownership even if marker exists
      chown ${TARGET_UID}:${TARGET_GID} "$d" || true
    fi
  done

  # Re-exec this script as the 'gameserver' user
  export START_SERVER_PRIVS_DROPPED=1
  if command -v runuser >/dev/null 2>&1; then
    exec runuser -u gameserver -- /usr/bin/start_server.sh
  else
    exec su -s /bin/bash -c "/usr/bin/start_server.sh" gameserver
  fi
fi

ENABLE_DEBUG="${ENABLE_DEBUG:-0}"
if [ "$ENABLE_DEBUG" = "1" ]; then
  echo "Entering debug mode..."
  sleep 999999999999
  exit 0
fi

STEAMCMD_DIR="/home/gameserver/steamcmd"
# download steamcmd if necessary
if [ ! -d "$STEAMCMD_DIR/linux32" ]; then
  mkdir -p "$STEAMCMD_DIR"
  cd "$STEAMCMD_DIR"
  wget https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz
  tar xfvz steamcmd_linux.tar.gz
fi

# download/update server files
cd "$STEAMCMD_DIR"
./steamcmd.sh +force_install_dir /home/gameserver/server-files +login anonymous +app_update 2430930 validate +quit

# Proton configuration
# - You can override by setting PROTON_VERSION (e.g., 9-xx)
# - If not set, we try to auto-detect the latest GE-Proton release via GitHub API
# - If detection fails, we fall back to a known-good default
DEFAULT_PROTON_VERSION="8-21"
if [ -z "${PROTON_VERSION:-}" ]; then
  echo "Detecting latest Proton GE version..."
  # Example tag_name: GE-Proton9-xx -> extract the 9-xx part
  if LATEST_TAG_JSON=$(wget -qO- https://api.github.com/repos/GloriousEggroll/proton-ge-custom/releases/latest 2>/dev/null || true); then
    if LATEST_NUMERIC=$(printf "%s" "$LATEST_TAG_JSON" | grep -m1 -o '"tag_name"\s*:\s*"GE-Proton[^"]*"' | sed -E 's/.*"GE-Proton([^"]*)".*/\1/' || true); then
      if [ -n "$LATEST_NUMERIC" ]; then
        PROTON_VERSION="$LATEST_NUMERIC"
        echo "Using latest detected GE-Proton version: $PROTON_VERSION"
      fi
    fi
  fi
fi
PROTON_VERSION="${PROTON_VERSION:-$DEFAULT_PROTON_VERSION}"
PROTON_DIR_NAME="GE-Proton$PROTON_VERSION"
PROTON_ARCHIVE_NAME="$PROTON_DIR_NAME.tar.gz"
STEAM_COMPAT_DATA=/home/gameserver/server-files/steamapps/compatdata
STEAM_COMPAT_DIR=/home/gameserver/Steam/compatibilitytools.d
ASA_COMPAT_DATA=$STEAM_COMPAT_DATA/2430930
ASA_BINARY_DIR="/home/gameserver/server-files/ShooterGame/Binaries/Win64"
START_PARAMS_FILE="/home/gameserver/server-files/start-parameters"
MODS="$(/usr/bin/cli-asa-mods.sh)"
ASA_START_PARAMS="${ASA_START_PARAMS:-} $MODS"
ASA_BINARY_NAME="ArkAscendedServer.exe"
ASA_PLUGIN_BINARY_NAME="AsaApiLoader.exe"
ASA_PLUGIN_LOADER_ARCHIVE_NAME=$(basename $ASA_BINARY_DIR/AsaApi_*.zip)
ASA_PLUGIN_LOADER_ARCHIVE_PATH="$ASA_BINARY_DIR/$ASA_PLUGIN_LOADER_ARCHIVE_NAME"
ASA_PLUGIN_BINARY_PATH="$ASA_BINARY_DIR/$ASA_PLUGIN_BINARY_NAME"
LAUNCH_BINARY_NAME="$ASA_BINARY_NAME"

# install proton if necessary
if [ ! -d "$STEAM_COMPAT_DIR/$PROTON_DIR_NAME" ]; then
  mkdir -p "$STEAM_COMPAT_DIR"
  echo "Downloading Proton GE-Proton$PROTON_VERSION... This might take a while"
  ASSET_BASE="https://github.com/GloriousEggroll/proton-ge-custom/releases/download/GE-Proton$PROTON_VERSION"
  ARCHIVE_URL="$ASSET_BASE/GE-Proton$PROTON_VERSION.tar.gz"
  SUM_URL="$ASSET_BASE/GE-Proton$PROTON_VERSION.sha512sum"
  LOCAL_ARCHIVE="/tmp/$PROTON_ARCHIVE_NAME"
  LOCAL_SUM_FILE="/tmp/GE-Proton$PROTON_VERSION.sha512sum"

  if ! wget -q -O "$LOCAL_ARCHIVE" "$ARCHIVE_URL"; then
    echo "Error: failed to download Proton archive."
    exit 200
  fi

  echo "Verifying sha512 checksum..."
  if wget -q -O "$LOCAL_SUM_FILE" "$SUM_URL"; then
    if (cd /tmp && sha512sum -c "$(basename "$LOCAL_SUM_FILE")" 2>/dev/null | grep -q "GE-Proton$PROTON_VERSION.tar.gz: OK"); then
      echo "Checksum OK."
    else
      echo "Error: sha512 checksum verification failed."
      if [ "${PROTON_SKIP_CHECKSUM:-0}" = "1" ]; then
        echo "PROTON_SKIP_CHECKSUM=1 set; continuing WITHOUT verification."
      else
        exit 201
      fi
    fi
    rm -f "$LOCAL_SUM_FILE" || true
  else
    echo "Warning: could not download checksum file." 
    if [ "${PROTON_SKIP_CHECKSUM:-0}" = "1" ]; then
      echo "PROTON_SKIP_CHECKSUM=1 set; continuing WITHOUT verification."
    else
      exit 201
    fi
  fi

  tar -xf "$LOCAL_ARCHIVE" -C "$STEAM_COMPAT_DIR"
  rm -f "$LOCAL_ARCHIVE"
fi

# install proton compat game data
if [ ! -d "$ASA_COMPAT_DATA" ]; then
  mkdir -p "$STEAM_COMPAT_DATA"
  cp -r "$STEAM_COMPAT_DIR/$PROTON_DIR_NAME/files/share/default_pfx" "$ASA_COMPAT_DATA"
fi

echo "Starting the ARK: Survival Ascended dedicated server..."
echo "Start parameters: $ASA_START_PARAMS"

#############################
# XDG_RUNTIME_DIR handling  #
#############################
# Proton expects a valid XDG runtime dir with 0700 perms.
# In minimal containers, /run/user/<uid> may not exist or be writable.
# Prefer a safe fallback under /tmp.
UID_CURRENT="$(id -u)"

# If provided, validate; otherwise pick a sane default.
if [ -n "${XDG_RUNTIME_DIR:-}" ]; then
  if [ ! -d "$XDG_RUNTIME_DIR" ] || [ ! -w "$XDG_RUNTIME_DIR" ]; then
    echo "Warning: XDG_RUNTIME_DIR '$XDG_RUNTIME_DIR' is not writable. Falling back to /tmp/xdg-runtime-$UID_CURRENT"
    XDG_RUNTIME_DIR="/tmp/xdg-runtime-$UID_CURRENT"
  fi
else
  CANDIDATE="/run/user/$UID_CURRENT"
  if [ -d "$CANDIDATE" ] && [ -w "$CANDIDATE" ]; then
    XDG_RUNTIME_DIR="$CANDIDATE"
  else
    XDG_RUNTIME_DIR="/tmp/xdg-runtime-$UID_CURRENT"
  fi
fi
export XDG_RUNTIME_DIR
export STEAM_COMPAT_CLIENT_INSTALL_PATH=/home/gameserver/Steam
export STEAM_COMPAT_DATA_PATH=$ASA_COMPAT_DATA

# Ensure runtime dir exists for Proton with correct perms (0700)
mkdir -p "$XDG_RUNTIME_DIR" || true
chmod 700 "$XDG_RUNTIME_DIR" 2>/dev/null || true

cd "$ASA_BINARY_DIR"

# unzip the asa plugin api archive if it exists. delete it afterwards
if [ -f "$ASA_PLUGIN_LOADER_ARCHIVE_PATH" ]; then
  unzip -o $ASA_PLUGIN_LOADER_ARCHIVE_NAME
  rm $ASA_PLUGIN_LOADER_ARCHIVE_NAME
fi

if [ -f "$ASA_PLUGIN_BINARY_PATH" ]; then
  echo "Detected ASA Server API loader. Launching server through $ASA_PLUGIN_BINARY_NAME"
  LAUNCH_BINARY_NAME="$ASA_PLUGIN_BINARY_NAME"
fi

# Stream server log files to the main console, if present
LOG_DIR="/home/gameserver/server-files/ShooterGame/Saved/Logs"
mkdir -p "$LOG_DIR"

# Start tailing known log patterns in the background. They might not exist yet; that's fine.
# This helps `docker logs -f` show the live server log content.
(
  # slight delay to avoid noisy errors before files are created
  sleep 1
  tail -n +1 -F "$LOG_DIR"/*.log "$LOG_DIR"/*.txt 2>/dev/null
) &

# Run Proton with line-buffered stdout/stderr so logs flush promptly (if available)
if command -v stdbuf >/dev/null 2>&1; then
  exec stdbuf -oL -eL "$STEAM_COMPAT_DIR/$PROTON_DIR_NAME/proton" run "$LAUNCH_BINARY_NAME" $ASA_START_PARAMS 2>&1
else
  exec "$STEAM_COMPAT_DIR/$PROTON_DIR_NAME/proton" run "$LAUNCH_BINARY_NAME" $ASA_START_PARAMS 2>&1
fi