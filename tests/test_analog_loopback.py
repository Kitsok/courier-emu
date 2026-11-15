"""Opt-in firmware AT&T1 echo regressions using operational defaults."""
import configparser
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import subprocess
import sys
import time
import tty

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.environ.get('COURIER_TEST_LOOPBACK') != '1',
                    reason='set COURIER_TEST_LOOPBACK=1 for a 60-second AT&T1 test')
@pytest.mark.parametrize('rate', [1, 2, 3], ids=['bell103-300', 'v22-1200', 'v22bis-2400'])
def test_firmware_analog_loopback_echoes_exact_data_for_60_seconds(tmp_path, rate):
    settings = configparser.ConfigParser(interpolation=None)
    settings.read(ROOT / 'courier-emu.ini')
    settings['modem'] = dict(profile='analog403', tty=str(tmp_path/'tty'),
                             serialsim='', nvram=str(tmp_path/'nvram.sav'))
    reservations = [socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for _ in range(2)]
    try:
        for sock in reservations:
            sock.bind(('127.0.0.1', 0))
        sip_port, rtp_port = [sock.getsockname()[1] for sock in reservations]
    finally:
        for sock in reservations:
            sock.close()
    settings['sip'] = dict(server='127.0.0.1:9', target='sip:{number}@127.0.0.1:9',
                           username='loopback-test', password_env='COURIER_LOOPBACK_UNUSED_PASSWORD',
                           bind='127.0.0.1', advertise='127.0.0.1', port=str(sip_port),
                           rtp_port=str(rtp_port), codec='pcmu')
    settings['logging'] = dict(level='quiet', report=str(tmp_path/'worker.json'))
    settings['audio'] = dict(enabled='false', volume='.25')
    settings['line'] = dict(tx_gain='.25', local_echo='false')
    with (tmp_path/'modem.ini').open('w') as output:
        settings.write(output)
    environment = os.environ.copy()
    environment.pop('COURIER_LOOPBACK_UNUSED_PASSWORD', None)
    received = bytearray()
    fd = None
    process = None
    packets = 0
    with (tmp_path/'runtime.txt').open('w') as log:
        try:
            process = subprocess.Popen(
                [sys.executable, '-m', 'courier_emu.runtime', '--config', str(tmp_path/'modem.ini')],
                cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True)

            def poll_until(predicate, timeout):
                deadline = time.monotonic() + timeout
                while not predicate():
                    assert process.poll() is None, 'runtime exited'
                    assert time.monotonic() < deadline, repr(bytes(received))
                    if fd is None:
                        time.sleep(.02)
                    elif select.select([fd], [], [], .02)[0]:
                        received.extend(os.read(fd, 8192))

            poll_until(lambda: (tmp_path/'tty').exists(), 60)
            fd = os.open(tmp_path/'tty', os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            tty.setraw(fd)
            os.write(fd, b'AT\r')
            poll_until(lambda: b'OK\r\n' in received, 30)
            received.clear()
            # The manual requires ARQ off and a fixed rate for AT&T1.
            # Use the profile's transmit level and normal modeled return.
            os.write(fd, f'ATE0&M0&N{rate}S14.0=0&T1\r'.encode('ascii'))
            poll_until(lambda: re.search(rb'CONNECT[^\r\n]*\r\n', received), 40)
            received.clear()
            start = time.monotonic()
            while time.monotonic() - start < 60:
                payload = f'{packets:06d}\r\n'.encode('ascii')
                assert os.write(fd, payload) == len(payload)
                poll_until(lambda: len(received) >= len(payload), 10)
                assert bytes(received[:len(payload)]) == payload
                del received[:len(payload)]
                packets += 1
            assert packets >= 100
            assert not received, repr(bytes(received))
            (tmp_path/'echo-result.json').write_text(json.dumps(dict(
                rate=[300, 1200, 2400][rate-1], packets=packets,
                exact_bytes=packets*8, seconds=time.monotonic()-start))+'\n')
        finally:
            (tmp_path/'terminal-tail.bin').write_bytes(received)
            if process is not None:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            if fd is not None:
                os.close(fd)
    report = json.loads((tmp_path/'worker.json').read_text())
    bridge = report['dsp_bridge']
    assert bridge['error'] is None
    assert not bridge['rx_acquisition_assist_enabled']
    assert not bridge['rx_acquisition_assisted']
    assert bridge['asic']['hybrid_return_on_hook'] == 64
    assert '001a:2fd6' in bridge['runtime_messages']
    assert bridge['serial_port']['codec_rx_peak'] < 32767
