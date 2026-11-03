#!/usr/bin/env python3
"""Build a separate DSP compiler variant without replacing the runtime library."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from courier_emu.dsp import LIBRARY, LIBRARY_SOURCES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', required=True, help='compiler executable path')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--extra-flag', action='append', default=[],
                        help='append one compiler flag; use --extra-flag=-FLAG')
    args = parser.parse_args()
    output = args.output.resolve()
    metadata = Path(str(output) + '.json')
    if output == LIBRARY.resolve() or output.exists() or metadata.exists():
        parser.error('choose a new output path outside the active runtime library')
    output.parent.mkdir(parents=True, exist_ok=True)
    version = subprocess.check_output([args.compiler, '--version'], text=True)
    flags = ['-std=c++17', '-O3', '-Wall', '-Wextra', '-Wpedantic',
             '-fno-semantic-interposition', '-pthread']
    flags += ['-dynamiclib'] if sys.platform == 'darwin' else ['-shared', '-fPIC']
    flags += args.extra_flag
    with tempfile.TemporaryDirectory(dir=output.parent) as folder:
        temporary = Path(folder) / output.name
        command = [args.compiler, *flags, *(str(p) for p in LIBRARY_SOURCES[:2]),
                   '-o', str(temporary)]
        subprocess.run(command, check=True)
        temporary.replace(output)
    manifest = dict(compiler_version=version, command=command,
                    source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in LIBRARY_SOURCES},
                    library_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    metadata.write_text(json.dumps(manifest, indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
