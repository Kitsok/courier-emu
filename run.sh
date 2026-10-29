#!/bin/sh
# Run the explicitly built analog runtime; no package installation at startup.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$root"
exec "${PYTHON:-python3}" -m courier_emu.runtime --config "$root/courier-emu.ini" "$@"
