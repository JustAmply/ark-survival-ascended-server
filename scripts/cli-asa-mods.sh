#!/bin/bash
# Wrapper to output enabled mods ensuring PYTHONPATH covers /usr/share
set -e -o pipefail
export PYTHONPATH="/usr/share:${PYTHONPATH:-}"
exec python3 -c 'from asa_ctrl.mods import format_mod_list_for_server; print(format_mod_list_for_server(), end="")' "$@"
