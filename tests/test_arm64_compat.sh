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
    # Try to source and execute the function
    source_result=$(source <(echo "$extract_error") 2>&1 && detect_architecture 2>&1 && echo "ARCH=$ARCH USE_BOX64=$USE_BOX64")
    if [ $? -eq 0 ] && echo "$source_result" | grep -q "ARCH="; then
        echo "  ✓ Architecture detection function works"
        echo "  $source_result"
    else
        echo "  ⊘ Could not test architecture detection (function may have dependencies)"
    fi
fi
echo

echo "=== All Tests Passed ==="
exit 0
