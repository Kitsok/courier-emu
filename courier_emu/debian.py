"""Build an analog-only Debian runtime package without installing it."""
from __future__ import annotations

import argparse
import configparser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from . import build, dsp, x86_native
from .boot_rom import MASK_ROM
from .profiles import ANALOG403_IMAGE

ROOT = Path(__file__).resolve().parent.parent


def copy(source, destination, mode=None):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(mode if mode is not None else 0o644)


def stage(destination: Path, version: str, architecture: str, libraries) -> None:
    lib = destination/'usr/lib/courier-emu'
    for source in (ROOT/'courier_emu').glob('*.py'):
        copy(source, lib/'courier_emu'/source.name)
    for source in libraries:
        copy(source, lib/'lib'/source.name, 0o644)
    for source in (ROOT/ANALOG403_IMAGE, MASK_ROM):
        copy(source, lib/source.relative_to(ROOT))
    (lib/'runtime.json').write_text(json.dumps({'python_abi':sys.implementation.cache_tag})+'\n')
    copy(ROOT/'packaging/courier-emu', destination/'usr/bin/courier-emu', 0o755)
    copy(ROOT/'packaging/courier-emu.service', destination/'usr/lib/systemd/system/courier-emu.service')
    copy(ROOT/'packaging/courier-emu.tmpfiles', destination/'usr/lib/tmpfiles.d/courier-emu.conf')
    copy(ROOT/'native/LICENSE', destination/'usr/share/doc/courier-emu/native-LICENSE')
    config = configparser.ConfigParser(interpolation=None)
    config.read(ROOT/'courier-emu.ini')
    config['modem']['tty']='/run/courier-emu/tty'
    config['modem']['nvram']='/var/lib/courier-emu/settings.nvram'
    # A system service has no desktop audio session by default.
    config['audio']['enabled']='false'
    path = destination/'etc/courier-emu/config.ini'
    path.parent.mkdir(parents=True)
    with path.open('w') as output:
        config.write(output)
    control = destination/'DEBIAN';control.mkdir()
    for name in ('postinst','prerm','postrm'):
        copy(ROOT/'packaging'/name, control/name, 0o755)
    (control/'conffiles').write_text('/etc/courier-emu/config.ini\n')
    # dpkg-shlibdeps reads source package identity from debian/control, but
    # determines the actual libc/libstdc++ minima from the built libraries.
    with tempfile.TemporaryDirectory(prefix='courier-shlibs-') as directory:
        work = Path(directory);(work/'debian').mkdir()
        (work/'debian/control').write_text('Source: courier-emu\n\nPackage: courier-emu\nArchitecture: any\nDescription: Analog Courier SIP emulator\n')
        result = subprocess.run(['dpkg-shlibdeps','-O',*[f'-e{p.resolve()}' for p in libraries]],
                                cwd=work, check=True, capture_output=True,text=True)
    shlibs = next(line.partition('=')[2] for line in result.stdout.splitlines()
                  if line.startswith('shlibs:Depends='))
    major,minor = sys.version_info[:2]
    depends = (f'python3 (>= {major}.{minor}~), python3 (<< {major}.{minor+1}), '
               f'{shlibs}, adduser, init-system-helpers, systemd')
    (control/'control').write_text(f'''Package: courier-emu
Version: {version}
Architecture: {architecture}
Maintainer: Courier emulator maintainers <root@localhost>
Section: comm
Priority: optional
Depends: {depends}
Suggests: tio, pulseaudio-utils
Description: Analog Courier firmware modem over SIP and RTP
 Runs the captured analog Courier supervisor and DSP with a stable serial
 terminal, native AT commands, G.711 media, and a systemd service.
''')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', default='0.1.0')
    parser.add_argument('--output', type=Path, default=ROOT/'dist')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[0-9][A-Za-z0-9.+~:-]*',args.version):
        parser.error('version is not a Debian version string')
    missing = [name for name in ('dpkg-deb','dpkg-shlibdeps','dpkg-architecture') if shutil.which(name) is None]
    if missing:
        parser.error('missing packaging prerequisites (Debian: dpkg-dev): '+', '.join(missing))
    if build.main([]):
        return 1
    architecture = subprocess.check_output(['dpkg-architecture','-qDEB_HOST_ARCH'],text=True).strip()
    libraries = [x86_native.build_library(),dsp.build_library()]
    args.output.mkdir(parents=True,exist_ok=True)
    output = args.output.resolve()/f'courier-emu_{args.version}_{architecture}.deb'
    with tempfile.TemporaryDirectory(prefix='courier-deb-') as directory:
        destination = Path(directory)/'root';destination.mkdir()
        stage(destination,args.version,architecture,libraries)
        subprocess.run(['dpkg-deb','--root-owner-group','--build',str(destination),str(output)],check=True)
    print(f'Debian package built: {output}; nothing was installed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
