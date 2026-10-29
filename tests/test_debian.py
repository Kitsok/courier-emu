from pathlib import Path
import json
import os
import select
import socket
import subprocess
import sys
import time

from courier_emu import debian, dsp, x86_native
from courier_emu.terminal import _pty_channel

ROOT = Path(__file__).resolve().parent.parent


def test_serial_pty_uses_service_primary_group_and_mode():
    master, slave, _ = _pty_channel()
    try:
        st = os.fstat(slave)
        assert st.st_gid == os.getgid()
        assert st.st_mode & 0o777 == 0o660
    finally:
        os.close(master);os.close(slave)


def test_package_loads_prebuilt_cores_and_operates_without_sources(tmp_path):
    root=tmp_path/'package';root.mkdir()
    debian.stage(root,'0.1.0-test','amd64',[x86_native.build_library(),dsp.build_library()])
    assert not (root/'usr/lib/courier-emu/native').exists()
    assert json.loads((root/'usr/lib/courier-emu/runtime.json').read_text())['python_abi']==sys.implementation.cache_tag
    assert '/etc/courier-emu/config.ini' in (root/'DEBIAN/conffiles').read_text()
    config=(root/'etc/courier-emu/config.ini').read_text()
    assert 'nvram = /var/lib/courier-emu/settings.nvram' in config
    path=tmp_path/'modem.ini'
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sip, socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as rtp:
        sip.bind(('127.0.0.1',0));rtp.bind(('127.0.0.1',0))
        sp,rp=sip.getsockname()[1],rtp.getsockname()[1]
    config=config.replace('/run/courier-emu/tty',str(tmp_path/'tty')).replace('/var/lib/courier-emu/settings.nvram',str(tmp_path/'settings.nvram')).replace('192.168.196.29:5060','127.0.0.1:9').replace('0.0.0.0','127.0.0.1').replace('port = 5074',f'port = {sp}').replace('rtp_port = 4014',f'rtp_port = {rp}')
    path.write_text(config)
    command=[str(root/'usr/bin/courier-emu'),'--config',str(path)]
    env=dict(os.environ,PATH='/nonexistent')
    subprocess.run(command+['--check-config'],env=env,check=True,capture_output=True)
    assert not (tmp_path/'settings.nvram').exists()
    log=(tmp_path/'log').open('w')
    process=subprocess.Popen(command,env=env,stdout=subprocess.DEVNULL,stderr=log)
    fd=None;data=b''
    try:
        deadline=time.monotonic()+35
        while time.monotonic()<deadline and process.poll() is None:
            if fd is None and (tmp_path/'tty').exists():
                fd=os.open(tmp_path/'tty',os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
                os.write(fd,b'AT\r')
            if fd is not None and select.select([fd],[],[],.1)[0]:
                data+=os.read(fd,8192)
                if b'OK' in data:break
        assert b'OK' in data
        assert '[at] command:' in (tmp_path/'log').read_text()
    finally:
        process.terminate()
        try:process.wait(timeout=20)
        except subprocess.TimeoutExpired:process.kill();process.wait()
        if fd is not None:os.close(fd)
        log.close()
    assert process.returncode==0
    assert not (tmp_path/'tty').is_symlink()
    # Fail clearly on an incompatible Python ABI instead of compiling.
    marker=root/'usr/lib/courier-emu/runtime.json'
    marker.write_text('{"python_abi":"wrong"}')
    result=subprocess.run(command+['--check-config'],env=env,capture_output=True,text=True)
    assert result.returncode==1
    assert 'different Python ABI' in result.stderr


def test_service_definition_with_isolated_systemd_prerequisites(tmp_path):
    import shutil
    root=tmp_path/'root'
    units=root/'usr/lib/systemd/system';units.mkdir(parents=True)
    shutil.copy(ROOT/'packaging/courier-emu.service',units/'courier-emu.service')
    target=root/'usr/bin/courier-emu';target.parent.mkdir(parents=True);target.write_text('#!/bin/sh\nexit 0\n');target.chmod(0o755)
    for name in ['sysinit.target','basic.target','shutdown.target','network-online.target','multi-user.target']:
        (units/name).write_text('[Unit]\nDescription=Test prerequisite\nDefaultDependencies=no\n')
    subprocess.run(['systemd-analyze','verify',f'--root={root}','courier-emu.service'],check=True,capture_output=True)


def test_postinst_preserves_disabled_service_and_creates_user(tmp_path):
    bin_dir=tmp_path/'bin';bin_dir.mkdir();log=tmp_path/'calls'
    for name in ['getent','adduser','systemd-tmpfiles','deb-systemd-helper','systemctl','deb-systemd-invoke']:
        script=bin_dir/name
        script.write_text('#!/bin/sh\nprintf "%s %s\\n" "${0##*/}" "$*" >> "$CALL_LOG"\n'
                          'case "${0##*/}:$*" in\n getent:*) exit 1;;\n '
                          'deb-systemd-helper:*was-enabled*) exit 1;;\n esac\n')
        script.chmod(0o755)
    env=dict(os.environ,PATH=str(bin_dir),CALL_LOG=str(log))
    subprocess.run(['/bin/sh',str(ROOT/'packaging/postinst'),'configure','0.1.0'],env=env,check=True)
    calls=log.read_text()
    assert 'adduser --system --ingroup dialout' in calls
    assert 'deb-systemd-helper update-state courier-emu.service' in calls
    assert 'deb-systemd-helper enable courier-emu.service' not in calls
