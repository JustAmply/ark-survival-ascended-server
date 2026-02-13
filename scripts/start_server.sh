#!/bin/bash
# Compatibility shim: startup runtime moved to standalone Python package.
set -euo pipefail
exec python -m server_runtime "$@"
