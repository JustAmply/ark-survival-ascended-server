#!/bin/bash
# Test script to verify Box64 wrapper creation logic
# This test validates that the ensure_wine_real_binaries function
# correctly creates Box64 wrapper scripts for Wine binaries

set -e

echo "=== Box64 Wrapper Creation Test ==="
echo

# Create a temporary directory for testing
TEST_DIR=$(mktemp -d)
trap "rm -rf $TEST_DIR" EXIT

# Create a mock Proton bin directory structure
BIN_DIR="$TEST_DIR/proton/files/bin"
mkdir -p "$BIN_DIR"

echo "Test 1: Creating mock Wine binaries"
# Create mock Wine binaries (simple executables)
for name in wine wine64 wine-preloader wine64-preloader; do
    echo -e "#!/bin/bash\necho 'Original $name binary'" > "$BIN_DIR/$name"
    chmod +x "$BIN_DIR/$name"
    echo "  ✓ Created mock $name"
done
echo

echo "Test 2: Extracting and running ensure_wine_real_binaries function"
# Extract the function from start_server.sh (use local path if /usr/bin version doesn't exist)
SCRIPT_PATH="/usr/bin/start_server.sh"
if [ ! -f "$SCRIPT_PATH" ]; then
    SCRIPT_PATH="$(dirname "$0")/../scripts/start_server.sh"
fi
FUNCTION_CODE=$(sed -n '/^ensure_wine_real_binaries()/,/^}$/p' "$SCRIPT_PATH")

if [ -z "$FUNCTION_CODE" ]; then
    echo "  ✗ Failed to extract ensure_wine_real_binaries function"
    exit 1
fi

# Set up test environment
export USE_BOX64=1
export STEAM_COMPAT_DIR="$TEST_DIR/proton/.."
export PROTON_DIR_NAME="proton"

# Define a mock log function
log() { echo "[test-log] $*"; }

# Source the function and execute it
eval "$FUNCTION_CODE"
ensure_wine_real_binaries
echo

echo "Test 3: Verifying .real binaries exist"
for name in wine wine64 wine-preloader wine64-preloader; do
    if [ -f "$BIN_DIR/$name.real" ]; then
        echo "  ✓ $name.real exists"
    else
        echo "  ✗ $name.real missing"
        exit 1
    fi
done
echo

echo "Test 4: Verifying wrapper scripts exist and are executable"
for name in wine wine64 wine-preloader wine64-preloader; do
    if [ -x "$BIN_DIR/$name" ]; then
        echo "  ✓ $name wrapper is executable"
    else
        echo "  ✗ $name wrapper is not executable"
        exit 1
    fi
done
echo

echo "Test 5: Verifying wrapper script content"
for name in wine wine64 wine-preloader wine64-preloader; do
    if grep -q "exec box64" "$BIN_DIR/$name"; then
        echo "  ✓ $name wrapper contains box64 exec call"
    else
        echo "  ✗ $name wrapper missing box64 exec call"
        cat "$BIN_DIR/$name"
        exit 1
    fi
done
echo

echo "Test 6: Verifying wrapper script is a bash script"
for name in wine wine64 wine-preloader wine64-preloader; do
    if head -n1 "$BIN_DIR/$name" | grep -q "^#!/bin/bash"; then
        echo "  ✓ $name wrapper has correct shebang"
    else
        echo "  ✗ $name wrapper has incorrect or missing shebang"
        exit 1
    fi
done
echo

echo "Test 7: Verifying idempotence (running function twice)"
# Run the function again to ensure it doesn't recreate wrappers
ensure_wine_real_binaries >/dev/null 2>&1
for name in wine wine64 wine-preloader wine64-preloader; do
    if [ -f "$BIN_DIR/$name.real" ] && grep -q "exec box64" "$BIN_DIR/$name"; then
        echo "  ✓ $name wrapper and .real remain intact after re-run"
    else
        echo "  ✗ $name wrapper or .real damaged after re-run"
        exit 1
    fi
done
echo

echo "=== All Tests Passed ==="
exit 0
