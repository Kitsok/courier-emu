#!/usr/bin/env python3
"""Profile standalone Courier training against a second loopback Courier.

All SIP/RTP addresses are loopback. Profiles cover SIP answer until both
firmware CONNECT results, excluding boot. Instrumentation changes timing;
these profiles attribute function work and do not measure unprofiled speed.
"""
import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import shutil
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
    from courier_emu.bridge import CourierDspBridge

    original_run, original_poll = CourierMachine.run, SipSession.poll
    profile = cProfile.Profile() if instrument else None
    measurement = {}
    machine = None
    work_enabled = os.environ.get('COURIER_DSP_WORK_PROFILE') == '1'
    work_core = None
    work_frames = work_first_frame = 0
    work_windows = []
    work_metadata = {}

    def collect_work():
        nonlocal work_frames
        bridge = machine.dsp_bridge
        if bridge.core is not work_core or work_core.closed:
            work_metadata['incomplete'] = 'DSP core was replaced or closed'
            return
        frames = int(bridge._sip_line.frames)
        work_windows.append(dict(first_frame=work_frames, end_frame=frames,
                                 wall=time.monotonic(), cpu=time.process_time(),
                                 core_state=work_core.state(), rows=work_core.work_profile()))
        work_core.clear_work_profile()
        work_frames = frames

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
            if work_enabled and work_core is not None:
                collect_work()
                (config.parent/'dsp-work.json').write_text(json.dumps(
                    dict(metadata=work_metadata, windows=work_windows), indent=2)+'\n')
                measurement['dsp_work'] = dict(file='dsp-work.json', windows=len(work_windows),
                                              incomplete=work_metadata.get('incomplete'))

    def poll(session):
        nonlocal work_core, work_frames, work_first_frame
        result = original_poll(session)
        if session.state == 'connected' and not measurement:
            measurement['start'] = snapshot()
            if work_enabled:
                work_core = machine.dsp_bridge.core
                if not work_core.clear_work_profile():
                    raise RuntimeError('--dsp-work requires a C5X_PROFILE_WORK library')
                work_frames = work_first_frame = int(machine.dsp_bridge._sip_line.frames)
                library = Path(work_core.library._name)
                work_metadata.update(library=str(library),
                    library_sha256=hashlib.sha256(library.read_bytes()).hexdigest(),
                    columns=['pc','executed','native','last_opcode','opcode_changes'],
                    first_frame=work_first_frame, frame_seconds=.1)
            if profile:
                profile.enable()
        if (work_enabled and work_core is not None and 'end' not in measurement
                and len(work_windows)<3 and not work_metadata.get('incomplete')
                and int(machine.dsp_bridge._sip_line.frames)>=work_first_frame+10*(len(work_windows)+1)):
            collect_work()
        return result

    original_close = CourierDspBridge.close
    def close(bridge):
        if machine is not None and bridge is machine.dsp_bridge:
            stop()  # Sample before the native core is destroyed.
        return original_close(bridge)
    if work_enabled:
        CourierDspBridge.close = close

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


def capture(output, timeout, instrument, batch_exits, rate_index=None, nvram_source=None, dsp_work=False):
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
    modem_failure = None
    started = time.monotonic()
    try:
        for role, port, rtp, peer in [('caller', a, ar, b), ('answerer', b, br, a)]:
            folder = output/role
            folder.mkdir()
            if nvram_source is not None:
                shutil.copyfile(nvram_source, folder/'nvram')
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
            if dsp_work:
                environment['COURIER_DSP_WORK_PROFILE'] = '1'
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
                    command = 'ATS0=1' if role == 'answerer' else 'AT'
                    if rate_index is not None:
                        command += f'&N{rate_index}&M5'
                    os.write(fds[role], (command+'\r').encode('ascii'))
            ready = select.select(list(fds.values()), [], [], .05)[0]
            for role, fd in fds.items():
                if fd in ready:
                    data[role] += os.read(fd, 8192)
            if not dialed and all(b'OK' in value for value in data.values()):
                os.write(fds['caller'], b'ATDT100\r')
                dialed = True
            if dialed:
                for role, value in data.items():
                    failure = re.search(rb'\r\n(NO CARRIER|BUSY|NO DIAL TONE|NO ANSWER)\r\n', value)
                    if failure:
                        modem_failure = dict(role=role, result=failure[1].decode('ascii'))
                        break
                if modem_failure:
                    break
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
                   dsp_work_profiled=dsp_work,
                   rate_index=rate_index, mandatory_arq=True,
                   nvram_source=str(nvram_source) if nvram_source else None,
                   nvram_source_sha256=(hashlib.sha256(nvram_source.read_bytes()).hexdigest()
                                        if nvram_source else None),
                   modem_failure=modem_failure,
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
    parser.add_argument('--dsp-work', action='store_true',
                        help='count executed DSP work by phase using a C5X_PROFILE_WORK library')
    parser.add_argument('--batch-exits', action='store_true',
                        help='count native exits and capture window boundaries')
    parser.add_argument('--rate-index', type=int, choices=(3, 6),
                        help='temporary &N3 (2400) or &N6 (9600), with &M5 ARQ')
    parser.add_argument('--nvram', type=Path,
                        help='copy this complete emulator EEPROM into both temporary profiles')
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
    if args.nvram is not None:
        from courier_emu.runtime import validated_nvram
        args.nvram = args.nvram.resolve()
        validated_nvram(args.nvram)
    return capture(args.output.resolve(), args.timeout, args.profile,
                   args.batch_exits, args.rate_index, args.nvram, args.dsp_work)


if __name__ == '__main__':
    raise SystemExit(main())
