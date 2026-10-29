"""Opt-in native firmware data test; no hardware, ATA edits or forced carrier."""
import os
from pathlib import Path
import re
import select
import socket
import subprocess
import time
import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(os.environ.get('COURIER_TEST_SIP_DATA') != '1',
                    reason='set COURIER_TEST_SIP_DATA=1 for the native SIP data test')
def test_native_courier_pair_negotiates_lapm_and_exchanges_exact_data(tmp_path):
    reservations = [socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for _ in range(4)]
    try:
        for sock in reservations:
            sock.bind(('127.0.0.1', 0))
        a, ar, b, br = [sock.getsockname()[1] for sock in reservations]
    finally:
        for sock in reservations:
            sock.close()
    processes, logs, fds = [], [], {}
    data = {'caller':b'', 'answerer':b''}
    markers = {'caller':b'CALLER-DATA-MARKER\r\n', 'answerer':b'ANSWERER-DATA-MARKER\r\n'}
    dialed = sent = False
    try:
        for role, port, rtp, peer in [('caller',a,ar,b),('answerer',b,br,a)]:
            folder = tmp_path/role;folder.mkdir()
            text = (ROOT/'courier-emu.ini').read_text()
            text = text.replace('192.168.196.29:5060',f'127.0.0.1:{peer}').replace('192.168.196.29','127.0.0.1')
            text = text.replace('0.0.0.0','127.0.0.1').replace('port = 5074',f'port = {port}').replace('rtp_port = 4014',f'rtp_port = {rtp}')
            text = text.replace('report =', 'report = '+str(folder/'worker.json'))
            config = folder/'modem.ini';config.write_text(text)
            log = (folder/'log').open('w');logs.append(log)
            processes.append(subprocess.Popen([str(ROOT/'run.sh'),'--config',str(config)],stdout=log,stderr=subprocess.STDOUT))
        deadline = time.monotonic()+180
        while time.monotonic()<deadline and all(p.poll() is None for p in processes):
            for role in data:
                path = tmp_path/role/'artifacts/courier-emu.tty'
                if role not in fds and path.exists():
                    fds[role] = os.open(path,os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
                    os.write(fds[role],b'ATS0=1\r' if role=='answerer' else b'AT\r')
            ready = select.select(list(fds.values()),[],[],.1)[0]
            for role,fd in fds.items():
                if fd in ready:
                    data[role] += os.read(fd,8192)
            if not dialed and all(b'OK' in d for d in data.values()):
                os.write(fds['caller'],b'ATDT100\r');dialed = True
            if not sent and all(re.search(rb'CONNECT[^\r\n]*/LAPM/V42BIS\r\n',d) for d in data.values()):
                for role,fd in fds.items():os.write(fd,markers[role])
                sent = True
            if markers['caller'] in data['answerer'] and markers['answerer'] in data['caller']:
                break
        assert sent, {role:repr(value[:200]) for role,value in data.items()}
        assert markers['caller'] in data['answerer'], repr(data['answerer'])
        assert markers['answerer'] in data['caller'], repr(data['caller'])
        # No forced carrier or acquisition assistance is used by the profile.
    finally:
        for p in processes:
            if p.poll() is None:p.terminate()
        for p in processes:
            try:p.wait(timeout=20)
            except subprocess.TimeoutExpired:p.kill();p.wait()
        for fd in fds.values():os.close(fd)
        for log in logs:log.close()
        for role,value in data.items():(tmp_path/role/'terminal.bin').write_bytes(value)

    import json
    for role in data:
        report=json.loads((tmp_path/role/'worker.json').read_text())
        assert report['dsp_bridge']['asic']['hybrid_return_off_hook']==0
        assert report['dsp_bridge']['sip']['sip']['transmit_gain']==.25
