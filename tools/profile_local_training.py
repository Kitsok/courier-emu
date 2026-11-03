#!/usr/bin/env python3
"""Profile standalone Courier training against a second loopback Courier.

All SIP/RTP addresses are loopback. Profiles cover SIP answer until both
firmware CONNECT results, excluding boot. Instrumentation changes timing;
these profiles attribute function work and do not measure unprofiled speed.
"""
import argparse
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def worker(config, instrument, arguments):
    import cProfile
    from courier_emu.machine import CourierMachine
    from courier_emu.sip import SipSession

    original_run, original_poll = CourierMachine.run, SipSession.poll
    profile = cProfile.Profile() if instrument else None
    measurement = {}
    machine = None

    def snapshot():
        native = machine.uc._native
        return dict(wall=time.monotonic(), cpu=time.process_time(),
                    instructions=machine.instructions, batches=native.batches,
                    zero_batches=native.zero_batches,
                    worker_yields=machine._worker_poll.yield_profile() if hasattr(machine, '_worker_poll') else {},
                    exits=[[list(key), value] for key, value in native.exits.items()])

    def stop(*_):
        if measurement and 'end' not in measurement:
            if profile:
                profile.disable()
            measurement['end'] = snapshot()

    def poll(session):
        result = original_poll(session)
        if session.state == 'connected' and not measurement:
            measurement['start'] = snapshot()
            if profile:
                profile.enable()
        return result

    def run(owner, *args, **kwargs):
        nonlocal machine
        machine = owner
        signal.signal(signal.SIGUSR2, stop)
        (config.parent/'worker.pid').write_text(str(os.getpid()))
        try:
            return original_run(owner, *args, **kwargs)
        finally:
            stop()
            if profile:
                profile.dump_stats(str(config.parent/'training.prof'))
            (config.parent/'window.json').write_text(json.dumps(measurement, indent=2)+'\n')

    CourierMachine.run, SipSession.poll = run, poll
    sys.argv = ['courier_emu.worker', *arguments]
    from courier_emu.worker import main
    return main()


def launch(config, instrument):
    from courier_emu import cli, runtime
    from courier_emu.terminal import run_console
    arguments, nvram = runtime.read_config(config)
    runtime.seed_nvram(nvram)
    args = cli.build_parser().parse_args(arguments)
    command = cli._worker_command(args)
    command = [sys.executable, str(Path(__file__).resolve()), '--execute',
               str(config), str(int(instrument)), *command[3:]]
    return run_console(args, command, cli._worker_environment(args))


def capture(output, timeout, instrument, batch_exits):
    output.mkdir(parents=True, exist_ok=False)
    reservations = [socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for _ in range(4)]
    try:
        for sock in reservations:
            sock.bind(('127.0.0.1', 0))
        a, ar, b, br = [sock.getsockname()[1] for sock in reservations]
    finally:
        for sock in reservations:
            sock.close()
    processes, logs, fds = {}, [], {}
    data = {'caller': b'', 'answerer': b''}
    markers = {'caller': b'CALLER-DATA-MARKER\r\n',
               'answerer': b'ANSWERER-DATA-MARKER\r\n'}
    dialed = sent = False
    started = time.monotonic()
    try:
        for role, port, rtp, peer in [('caller', a, ar, b), ('answerer', b, br, a)]:
            folder = output/role
            folder.mkdir()
            settings = configparser.ConfigParser(interpolation=None)
            settings.read(ROOT/'courier-emu.ini')
            settings['sip'].update(server=f'127.0.0.1:{peer}',
                                   target=f'sip:{{number}}@127.0.0.1:{peer}',
                                   bind='127.0.0.1', advertise='127.0.0.1',
                                   port=str(port), rtp_port=str(rtp))
            settings['audio']['enabled'] = 'false'
            settings['logging']['report'] = str(folder/'worker.json')
            settings['modem']['serialsim'] = ''
            settings['modem']['nvram'] = str(folder/'nvram')
            settings['modem']['tty'] = str(folder/'modem.tty')
            config = folder/'modem.ini'
            with config.open('w') as stream:
                settings.write(stream)
            log = (folder/'log').open('w')
            logs.append(log)
            command = [sys.executable, str(Path(__file__).resolve()), '--worker', str(config)]
            if instrument:
                command.append('--profile')
            environment = os.environ.copy()
            if batch_exits:
                environment['COURIER_X86_PROFILE'] = '1'
            processes[role] = subprocess.Popen(command, cwd=ROOT, stdout=log,
                                                stderr=subprocess.STDOUT, env=environment)
        deadline = started+timeout
        while time.monotonic() < deadline and all(p.poll() is None for p in processes.values()):
            for role in data:
                path = output/role/'modem.tty'
                if role not in fds and path.exists():
                    fds[role] = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
                    os.write(fds[role], b'ATS0=1\r' if role == 'answerer' else b'AT\r')
            ready = select.select(list(fds.values()), [], [], .05)[0]
            for role, fd in fds.items():
                if fd in ready:
                    data[role] += os.read(fd, 8192)
            if not dialed and all(b'OK' in value for value in data.values()):
                os.write(fds['caller'], b'ATDT100\r')
                dialed = True
            if not sent and all(re.search(rb'CONNECT[^\r\n]*/LAPM/V42BIS\r\n', value)
                                for value in data.values()):
                for role, process in processes.items():
                    pid = int((output/role/'worker.pid').read_text())
                    os.kill(pid, signal.SIGUSR2)
                    os.write(fds[role], markers[role])
                sent = True
            if markers['caller'] in data['answerer'] and markers['answerer'] in data['caller']:
                break
    finally:
        for process in processes.values():
            if process.poll() is None:
                process.terminate()
        for process in processes.values():
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for fd in fds.values():
            os.close(fd)
        for log in logs:
            log.close()
        for role, value in data.items():
            (output/role/'terminal.bin').write_bytes(value)
    success = sent and all(markers[peer] in data[role]
                           for role, peer in [('caller', 'answerer'), ('answerer', 'caller')])
    summary = dict(instrumented=instrument, batch_exits_counted=batch_exits,
                   exact_bidirectional_data=success,
                   elapsed_seconds=time.monotonic()-started, endpoints={})
    for role, value in data.items():
        summary['endpoints'][role] = {'terminal': value.decode('ascii', errors='replace')}
        window = output/role/'window.json'
        if window.exists():
            summary['endpoints'][role]['window'] = json.loads(window.read_text())
    (output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary, indent=2))
    return 0 if success else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--profile', action='store_true')
    parser.add_argument('--batch-exits', action='store_true',
                        help='count native exits and capture window boundaries')
    parser.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--execute', nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.execute:
        config, instrument, *arguments = args.execute
        return worker(Path(config), bool(int(instrument)), arguments)
    if args.worker:
        return launch(args.worker, args.profile)
    if args.output is None or args.timeout <= 0:
        parser.error('--output and a positive --timeout are required')
    return capture(args.output.resolve(), args.timeout, args.profile, args.batch_exits)


if __name__ == '__main__':
    raise SystemExit(main())
