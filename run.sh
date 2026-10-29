#!/bin/sh
# Run the explicitly built analog runtime; no package installation at startup.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$root"
# Register extension 201 with the PBX configured in courier-emu.ini.
exec "${PYTHON:-python3}" -m courier_emu.runtime --config "$root/courier-emu.ini" --sip-register "$@"
