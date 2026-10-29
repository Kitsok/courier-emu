#!/bin/sh
# Build the analog Courier runtime without installing packages or a virtualenv.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python=${PYTHON:-python3}
command -v "$python" >/dev/null 2>&1 || {
    printf '%s\n' 'build.sh: Python 3.10+ is required (Debian: python3 python3-dev).' >&2
    exit 1
}
cd "$root"
exec "$python" -m courier_emu.build "$@"
