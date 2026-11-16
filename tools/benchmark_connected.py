#!/usr/bin/env python3
"""Measure a verified local SIP modem pair; never contact hardware or a PBX."""
from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import re
import select
import signal
import socket
import subprocess
import sys
import time
import tty

ROOT = Path(__file__).resolve().parents[1]
ROLES = ('caller', 'answerer')


def process_cpu(pid):
    """Linux process-tree CPU seconds, excluding the benchmark driver."""
    text = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    total = (int(text[11]) + int(text[12])) / os.sysconf('SC_CLK_TCK')
    children = Path(f'/proc/{pid}/task/{pid}/children').read_text().split()
    return total + sum(process_cpu(int(child)) for child in children)


class Pair:
    def __init__(self, output):
        self.output = output
        self.processes, self.logs, self.fds = {}, [], {}
        self.transcripts = {role: bytearray() for role in ROLES}

    def start(self):
        reservations = [socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for _ in range(4)]
        try:
            for sock in reservations:
                sock.bind(('127.0.0.1', 0))
            ports = [sock.getsockname()[1] for sock in reservations]
        finally:
            for sock in reservations:
                sock.close()
        for role, port, rtp, peer in [('caller', ports[0], ports[1], ports[2]),
                                      ('answerer', ports[2], ports[3], ports[0])]:
            folder = self.output / role
            folder.mkdir()
            config = configparser.ConfigParser(interpolation=None)
            config.read(ROOT/'courier-emu.ini')
            username = config['sip']['username']
            config['modem'] = dict(profile='analog403', tty=str(folder/'tty'),
                                   serialsim='', nvram=str(folder/'nvram.sav'))
            config['sip'] = dict(server=f'127.0.0.1:{peer}', target=f'sip:{{number}}@127.0.0.1:{peer}',
                                 username=username, password_env='COURIER_BENCHMARK_NO_PASSWORD',
                                 bind='127.0.0.1', advertise='127.0.0.1', port=str(port),
                                 rtp_port=str(rtp), codec='pcmu')
            config['logging'] = dict(level='quiet', report=str(folder/'worker.json'))
            config['audio'] = dict(enabled='false', volume='.25')
            config['line'] = dict(tx_gain='.25', local_echo='false')
            with (folder/'modem.ini').open('w') as stream:
                config.write(stream)
            log = (folder/'runtime.txt').open('w')
            self.logs.append(log)
            environment = os.environ.copy()
            environment['PYTHON'] = sys.executable
            environment.pop('COURIER_BENCHMARK_NO_PASSWORD', None)
            self.processes[role] = subprocess.Popen(
                [str(ROOT/'run.sh'), '--config', str(folder/'modem.ini')],
                cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True)

    def poll(self, timeout=.02):
        for role, process in self.processes.items():
            if process.poll() is not None:
                raise RuntimeError(f'{role} exited with {process.returncode}')
            path = self.output/role/'tty'
            if role not in self.fds and path.exists():
                fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
                tty.setraw(fd)
                self.fds[role] = fd
                os.write(fd, b'ATS0=1\r' if role == 'answerer' else b'AT\r')
        ready = select.select(list(self.fds.values()), [], [], timeout)[0]
        for role, fd in self.fds.items():
            if fd in ready:
                try:
                    chunk = os.read(fd, 8192)
                except BlockingIOError:
                    continue
                if not chunk:
                    raise RuntimeError(f'{role} terminal closed')
                self.transcripts[role].extend(chunk)

    def wait_for(self, predicate, timeout, *, carrier=False):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                raise TimeoutError('modem setup/handshake timed out')
            self.poll()
            if carrier and any(b'NO CARRIER' in data for data in self.transcripts.values()):
                raise RuntimeError('firmware returned NO CARRIER before the data window')

    def cpu(self):
        return {role: process_cpu(p.pid) for role, p in self.processes.items()}

    def close(self):
        for role in ROLES:
            (self.output/role).mkdir(exist_ok=True)
            (self.output/role/'terminal.bin').write_bytes(self.transcripts[role])
        for process in self.processes.values():
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for process in self.processes.values():
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        # The runtime launches a worker child in its own process group.
        # Give workers time to publish reports, then ensure no group remains.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                for role in ROLES:
                    json.loads((self.output/role/'worker.json').read_text())
                break
            except (FileNotFoundError, ValueError):
                pass
            time.sleep(.05)
        for process in self.processes.values():
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for fd in self.fds.values():
            os.close(fd)
        for log in self.logs:
            log.close()


def transfer(pair, duration, rates, drain_timeout, *, payload='binary'):
    sent = {r: bytearray() for r in ROLES}
    received = dict.fromkeys(ROLES, 0)
    hashes = {r: hashlib.sha256() for r in ROLES}
    rng = {r: random.Random(403 + i) for i, r in enumerate(ROLES)}
    pending = dict.fromkeys(ROLES, b'')
    tokens = dict.fromkeys(ROLES, 0.)
    for role in ROLES:
        (pair.output/role/'negotiation.bin').write_bytes(pair.transcripts[role])
    pair.transcripts = {r: bytearray() for r in ROLES}
    before = pair.cpu()
    start = last = time.monotonic()
    progress = start + 10
    window_received = None
    after = None
    while True:
        now = time.monotonic()
        active = now - start < duration
        if not active and window_received is None:
            window_received = dict(received)
            after = pair.cpu()
            window_wall = now - start
        if not active and all(received[r] == len(sent[ROLES[1-i]]) for i, r in enumerate(ROLES)):
            break
        if now - start >= duration + drain_timeout:
            raise TimeoutError(f'payload drain timed out: sent={ {r:len(v) for r,v in sent.items()} }, received={received}')
        if active:
            for r in ROLES:
                tokens[r] = min(128., tokens[r] + (now - last) * rates[r])
        last = now
        pair.poll(.01)
        for i, role in enumerate(ROLES):
            chunk = bytes(pair.transcripts[role])
            pair.transcripts[role].clear()
            expected = sent[ROLES[1-i]][received[role]:received[role]+len(chunk)]
            if chunk != expected:
                (pair.output/role/'mismatch.bin').write_bytes(chunk)
                raise RuntimeError(f'{role} payload mismatch at byte {received[role]}')
            received[role] += len(chunk)
            hashes[role].update(chunk)
        if active:
            writable = select.select([], list(pair.fds.values()), [], 0)[1]
            for role, fd in pair.fds.items():
                if fd not in writable or tokens[role] < 1:
                    continue
                if not pending[role]:
                    if payload == 'binary':
                        pending[role] = rng[role].randbytes(128)
                    else:
                        alphabet = bytes(value for value in range(32, 127) if value != 43)
                        pending[role] = bytes(rng[role].choice(alphabet) for _ in range(128))
                part = pending[role][:int(tokens[role])]
                try:
                    count = os.write(fd, part)
                except BlockingIOError:
                    continue
                sent[role].extend(part[:count])
                pending[role] = pending[role][count:]
                tokens[role] -= count
        if now >= progress:
            print(json.dumps(dict(phase='transfer', seconds=round(now-start, 1), received=received)), flush=True)
            progress += 10
    if not all(sent.values()):
        raise RuntimeError('no payload transferred in one or both directions')
    return dict(window_wall_seconds=window_wall, cpu_seconds={r:after[r]-before[r] for r in ROLES},
                offered_bytes_per_second=rates, sent_bytes={r:len(v) for r,v in sent.items()},
                received_bytes=received, received_in_window=window_received,
                delivered_bytes_per_second={r:window_received[r]/window_wall for r in ROLES},
                sent_sha256={r:hashlib.sha256(v).hexdigest() for r,v in sent.items()},
                received_sha256={r:v.hexdigest() for r,v in hashes.items()},
                drain_seconds=time.monotonic()-start-window_wall)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--duration', type=float, default=60)
    parser.add_argument('--setup-timeout', type=float, default=180)
    parser.add_argument('--drain-timeout', type=float, default=30)
    parser.add_argument('--bytes-per-second', type=float,
                        help='explicit offered payload rate per direction; default is 75%% of negotiated baud / 10')
    parser.add_argument('--payload', choices=('binary', 'printable'), default='binary')
    args = parser.parse_args()
    if min(args.duration, args.setup_timeout, args.drain_timeout) <= 0:
        parser.error('durations must be positive')
    if args.bytes_per_second is not None and args.bytes_per_second <= 0:
        parser.error('bytes-per-second must be positive')
    output = args.output.resolve()
    output.mkdir(parents=True)
    pair = Pair(output)
    result = dict(status='starting', revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                  platform=platform.platform(), python=platform.python_version(), duration=args.duration,
                  command=sys.argv, offered_fraction=.75, seeds=dict(caller=403, answerer=404))
    result['explicit_bytes_per_second'] = args.bytes_per_second
    result['payload'] = args.payload
    result['optimization_switches'] = {name: os.environ.get(name, '1') for name in (
        'COURIER_WORKER_CONFIG', 'COURIER_NATIVE_TIMER2_PROGRAMMING',
        'COURIER_NATIVE_LINE_CLOCK', 'COURIER_NATIVE_LANE_PENDING')}
    try:
        pair.start()
        start = time.monotonic()
        print('Waiting for both firmware AT interfaces', flush=True)
        pair.wait_for(lambda: all(b'OK' in v for v in pair.transcripts.values()), args.setup_timeout)
        os.write(pair.fds['caller'], b'ATDT100\r')
        print('Dialling local peer; waiting for firmware CONNECT', flush=True)
        pattern = rb'CONNECT[^\r\n]*\r\n'
        pair.wait_for(lambda: all(re.search(pattern,v) for v in pair.transcripts.values()),
                      args.setup_timeout, carrier=True)
        connect = {r:re.search(pattern,v).group().decode('ascii').strip() for r,v in pair.transcripts.items()}
        result.update(connect=connect, setup_wall_seconds=time.monotonic()-start)
        markers = {r:('BENCH-HELLO-'+r.upper()+'\r\n').encode() for r in ROLES}
        for r in ROLES:
            os.write(pair.fds[r], markers[r])
        pair.wait_for(lambda: all(markers[ROLES[1-i]] in pair.transcripts[r] for i,r in enumerate(ROLES)),
                      30, carrier=True)
        rates = {r:int(re.search(r'CONNECT\s+(\d+)',line).group(1)) / 10 * .75 for r,line in connect.items()}
        if args.bytes_per_second is not None:
            rates = dict.fromkeys(ROLES, args.bytes_per_second)
        print(json.dumps(dict(phase='connected', connect=connect, offered_bytes_per_second=rates)), flush=True)
        result.update(transfer(pair,args.duration,rates,args.drain_timeout,payload=args.payload), status='passed')
    except Exception as error:
        result.update(status='failed', error=f'{type(error).__name__}: {error}')
        print(result['error'], flush=True)
    finally:
        pair.close()
        (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    return 0 if result['status']=='passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
