#!/bin/bash
# Wrapper for box86 on ARM64
if [ "$(uname -m)" = "aarch64" ]; then
    exec box86 "$@"
else
    exec "$@"
fi
