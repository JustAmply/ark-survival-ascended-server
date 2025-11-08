#!/bin/bash
# Test script to verify ARM64 compatibility features
# This can be run inside the Docker container to validate setup

set -e

echo "=== ARM64 Compatibility Test ==="
echo

# Test 1: Architecture detection
echo "Test 1: Architecture Detection"
ARCH=$(uname -m)
echo "  Detected architecture: $ARCH"
case "$ARCH" in
    x86_64|amd64)
        echo "  ✓ AMD64 architecture detected"
        EXPECTED_BOX64=false
        ;;
    aarch64|arm64)
        echo "  ✓ ARM64 architecture detected"
        EXPECTED_BOX64=true
        ;;
    *)
        echo "  ✗ Unknown architecture: $ARCH"
        exit 1
        ;;
esac
echo

# Test 2: Box64 availability on ARM64
echo "Test 2: Box64 Availability"
if [ "$EXPECTED_BOX64" = true ]; then
    if command -v box64 >/dev/null 2>&1; then
        echo "  ✓ Box64 is installed"
        BOX64_VERSION=$(box64 --version 2>&1 | head -n1 || echo "version unknown")
        echo "  Box64 version: $BOX64_VERSION"
    else
        echo "  ✗ Box64 is NOT installed (required for ARM64)"
        exit 1
    fi
else
    echo "  ⊘ Box64 not required on AMD64"
fi
echo

# Test 3: Box86 availability on ARM64
echo "Test 3: Box86 Availability"
if [ "$EXPECTED_BOX64" = true ]; then
    if command -v box86 >/dev/null 2>&1; then
        echo "  ✓ Box86 is installed"
        BOX86_VERSION=$(box86 --version 2>&1 | head -n1 || echo "version unknown")
        echo "  Box86 version: $BOX86_VERSION"
        if [ -e "/lib/ld-linux.so.2" ]; then
            echo "  ✓ 32-bit x86 loader (/lib/ld-linux.so.2) is present"
        else
            echo "  ✗ 32-bit x86 loader (/lib/ld-linux.so.2) is missing"
            exit 1
        fi
        if [ -d "/usr/lib/box86-i386-linux-gnu" ]; then
            echo "  ✓ Box86 compatibility libraries are installed"
        else
            echo "  ✗ Box86 compatibility libraries directory is missing"
            exit 1
        fi
        if grep -q "BOX86_LD_LIBRARY_PATH" /usr/bin/start_server.sh; then
            echo "  ✓ start_server.sh configures Box86 runtime paths"
        else
            echo "  ✗ start_server.sh missing Box86 runtime path configuration"
            exit 1
        fi
        if grep -q "DEBUGGER=box86" /usr/bin/start_server.sh; then
            echo "  ✓ start_server.sh routes steamcmd through box86"
        else
            echo "  ✗ start_server.sh missing box86 steamcmd routing"
            exit 1
        fi
    else
        echo "  ✗ Box86 is NOT installed (required for ARM64 SteamCMD)"
        exit 1
    fi
else
    echo "  ⊘ Box86 not required on AMD64"
fi
echo

# Test 4: Required directories exist
echo "Test 4: Directory Structure"
REQUIRED_DIRS=(
    "/home/gameserver/Steam"
    "/home/gameserver/steamcmd"
    "/home/gameserver/server-files"
    "/home/gameserver/cluster-shared"
)
for dir in "${REQUIRED_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        echo "  ✓ $dir exists"
    else
        echo "  ✗ $dir is missing"
        exit 1
    fi
done
echo

# Test 5: Python asa_ctrl is available
echo "Test 5: asa_ctrl CLI"
if command -v asa-ctrl >/dev/null 2>&1; then
    echo "  ✓ asa-ctrl command is available"
    # Try to run a simple command
    if asa-ctrl --help >/dev/null 2>&1; then
        echo "  ✓ asa-ctrl executes successfully"
    else
        echo "  ✗ asa-ctrl command failed"
        exit 1
    fi
else
    echo "  ✗ asa-ctrl command not found"
    exit 1
fi
echo

# Test 6: Start script is executable
echo "Test 6: Start Script"
if [ -x "/usr/bin/start_server.sh" ]; then
    echo "  ✓ start_server.sh is executable"
else
    echo "  ✗ start_server.sh is not executable"
    exit 1
fi
echo

# Test 7: Test architecture detection via script execution
echo "Test 7: Start Script Architecture Functions"
# Extract and test the detect_architecture function
extract_error=$(sed -n '/^detect_architecture()/,/^}/p' /usr/bin/start_server.sh 2>&1)
if [ $? -ne 0 ]; then
    echo "  ⊘ Could not extract architecture detection function: $extract_error"
else
    # Source the function and call it in the current shell so that ARCH and USE_BOX64 are set here
    eval "$extract_error"
    detect_architecture
    if [ -n "$ARCH" ] && [ -n "$USE_BOX64" ]; then
        echo "  ✓ Architecture detection function works"
        echo "  ARCH=$ARCH USE_BOX64=$USE_BOX64"
    else
        echo "  ⊘ Could not test architecture detection (ARCH/USE_BOX64 not set; function may have dependencies)"
    fi
fi
echo

echo "Test 8: Box64 GnuTLS Compat Shim"
COMPAT_BASE="/usr/lib/box64-compat"
if [ -d "$COMPAT_BASE" ]; then
    status=0
    for arch_dir in x86_64-linux-gnu i386-linux-gnu; do
        compat_lib="$COMPAT_BASE/$arch_dir/libgnutls.so.30"
        if [ ! -f "$compat_lib" ]; then
            echo "  ✗ Missing $compat_lib"
            status=1
            continue
        fi
        if nm -D "$compat_lib" | grep -q '_gnutls_ecdh_compute_key$'; then
            echo "  ✓ $arch_dir libgnutls exports _gnutls_ecdh_compute_key"
        else
            echo "  ✗ $arch_dir libgnutls lacks _gnutls_ecdh_compute_key"
            status=1
        fi
    done
    if [ $status -ne 0 ]; then
        exit 1
    fi
else
    echo "  ⊘ Compat shim directory missing; has the image been rebuilt?"
    exit 1
fi
echo

echo "Test 9: Proton Compat Load (best effort)"
if [ "$EXPECTED_BOX64" = true ]; then
    proton_launcher=$(find /home/gameserver/Steam/compatibilitytools.d -maxdepth 2 -type f -name proton 2>/dev/null | head -n1 || true)
    if [ -z "$proton_launcher" ]; then
        echo "  ⊘ Proton not installed yet; skipping load-path validation"
    else
        compat64="$COMPAT_BASE/x86_64-linux-gnu"
        compat32="$COMPAT_BASE/i386-linux-gnu"
        compat_ld=""
        compat_paths=()
        [ -d "$compat64" ] && compat_paths+=("$compat64")
        [ -d "$compat32" ] && compat_paths+=("$compat32")
        if [ ${#compat_paths[@]} -gt 0 ]; then
            compat_ld=$(IFS=:; echo "${compat_paths[*]}")
        fi
        tmp_log=$(mktemp)
        export STEAM_COMPAT_CLIENT_INSTALL_PATH="/home/gameserver/Steam"
        export STEAM_COMPAT_DATA_PATH="/tmp/test-proton-compat"
        mkdir -p "$STEAM_COMPAT_DATA_PATH"
        ld_merge="${LD_LIBRARY_PATH:-}"
        if [ -n "$compat_ld" ]; then
            if [ -n "$ld_merge" ]; then
                ld_merge="$compat_ld:$ld_merge"
            else
                ld_merge="$compat_ld"
            fi
        fi
        if timeout 30s env BOX64_LOG=0 WINEDEBUG=+loaddll LD_LIBRARY_PATH="$ld_merge" "$proton_launcher" run /bin/true >"$tmp_log" 2>&1; then
            if grep -q "/usr/lib/box64-compat/x86_64-linux-gnu/libgnutls.so.30" "$tmp_log"; then
                echo "  ✓ Proton loaded libgnutls from compat path"
            else
                echo "  ✗ Proton did not load libgnutls from compat path"
                sed -n '1,80p' "$tmp_log"
                rm -rf "$tmp_log" "$STEAM_COMPAT_DATA_PATH"
                exit 1
            fi
        else
            echo "  ⊘ Proton test invocation failed; output follows"
            sed -n '1,120p' "$tmp_log"
            rm -rf "$tmp_log" "$STEAM_COMPAT_DATA_PATH"
            exit 1
        fi
        rm -rf "$tmp_log" "$STEAM_COMPAT_DATA_PATH"
    fi
else
    echo "  ⊘ Proton compat test skipped on AMD64 host"
fi
echo

echo "=== All Tests Passed ==="
exit 0
