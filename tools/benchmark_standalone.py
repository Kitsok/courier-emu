#!/usr/bin/env python3
"""Repeatable standalone 403 DSP/SIP CPU measurement against a loopback sink.

This measures boot plus idle or dialing, not a negotiated modem data call.
The reserved UDP endpoint consumes no external service and sends no responses.
"""
import argparse
import cProfile
import hashlib
import json
from pathlib import Path
import platform
import socket
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class WindowConsole:
    """Observe a running machine at console deadlines, without guest hooks."""

    poll_instructions = 8192
    closed = False

    def __init__(self, warmup, stop, profile):
        self.warmup, self.stop, self.profile = warmup, stop, profile
        self.owner = None
        self.start = self.end = None

    def snapshot(self):
        m = self.owner
        native = m.uc._native
        poll = getattr(m, '_worker_poll', None)
        return dict(wall=time.perf_counter(), cpu=time.process_time(),
                    instructions=m.instructions, mmio=m.mmio_counts.copy(),
                    io=m.io_counts.copy(), exits=native.exits.copy(),
                    batches=native.batches, retired=native.retired,
                    zero_batches=native.zero_batches,
                    polls=poll.state.polls if poll else 0,
                    dsp_batches=poll.state.dsp_batches if poll else 0)

    def poll(self, limit):
        if self.start is None and self.owner.instructions >= self.warmup:
            self.start = self.snapshot()
            if self.profile:
                self.profile.enable()
        elif self.start is not None and self.end is None and self.owner.instructions >= self.stop:
            if self.profile:
                self.profile.disable()
            self.end = self.snapshot()
        return b''

    def wait(self, seconds):
        time.sleep(seconds)
        return False

    def write(self, byte):
        pass

    def show_lamps(self, line):
        pass

    def close(self):
        pass

    def summary(self):
        return {}


def counter_report(counts):
    return [[list(key), count] for key, count in counts.most_common(30)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instructions', type=int, default=30_000_000)
    parser.add_argument('--dial', action='store_true')
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--warmup-instructions', type=int, default=0,
                        help='exclude boot; observe the following --instructions window through console polls')
    parser.add_argument('--profile-out', type=Path,
                        help='cProfile only the measured console window; requires --repeat 1')
    args = parser.parse_args()
    if args.instructions <= 0 or args.repeat <= 0 or args.warmup_instructions < 0:
        parser.error('instructions/repeat must be positive and warmup nonnegative')
    if args.profile_out and args.repeat != 1:
        parser.error('--profile-out requires --repeat 1')
    if (args.warmup_instructions or args.profile_out) and args.instructions <= 16384:
        parser.error('console measurement windows must exceed 16384 instructions')

    from courier_emu.codec import CodecBringUp, SiliconDaa
    from courier_emu.daa import CourierDaa
    from courier_emu.dsp import build_library
    from courier_emu.exchange import LineExchange
    from courier_emu.images import load_image
    from courier_emu.machine import CourierMachine
    from courier_emu.nvram import CourierNvram
    from courier_emu.profiles import ROOT, ANALOG403_IMAGE
    from courier_emu.sip import SipConfig, SipSession
    from courier_emu.x86_native import build_library as build_x86

    build_library()
    build_x86()
    image = load_image(ROOT / ANALOG403_IMAGE)
    runs = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sink:
        sink.bind(('127.0.0.1', 0))
        for _ in range(args.repeat):
            profile = cProfile.Profile() if args.profile_out else None
            console = (WindowConsole(args.warmup_instructions,
                                     args.warmup_instructions + args.instructions - 8192, profile)
                       if args.warmup_instructions or profile else None)
            sip = SipSession(SipConfig(
                server='127.0.0.1:' + str(sink.getsockname()[1]),
                bind='127.0.0.1', advertise='127.0.0.1'))
            try:
                machine = CourierMachine(
                    image, with_dsp=True,
                    nvram=CourierNvram.idsl403_lapm_fixture(), board_id=7,
                    serial_input=b'ATDT100\r' if args.dial and not console else b'',
                    serial_input_schedule=[(args.warmup_instructions, b'ATDT100\r')]
                    if args.dial and console else [],
                    daa=CourierDaa('quiet'), exchange=LineExchange(),
                    codec=CodecBringUp(SiliconDaa(1)), dsp_batch=4096,
                    tick_source='dsp', sip=sip, console=console)
                if console:
                    console.owner = machine
                wall, cpu = time.perf_counter(), time.process_time()
                result = machine.run(args.warmup_instructions + args.instructions)
                if profile:
                    profile.disable()
                end = (console.end or console.snapshot()) if console else None
                cpu = time.process_time() - cpu
                wall = time.perf_counter() - wall
                result = result.to_dict()
                if profile:
                    profile.dump_stats(str(args.profile_out))
                record = dict(
                    wall_seconds=wall, cpu_seconds=cpu,
                    instructions=machine.instructions,
                    instructions_per_cpu_second=machine.instructions / cpu,
                    realtime_cpu_multiple=(machine.instructions / cpu
                                           / machine.timebase.instructions_per_second),
                    status=result['status'], scheduler=result['scheduler'],
                    memory_sha256=hashlib.sha256(machine.uc.memory).hexdigest(),
                    registers=list(machine.uc.regs),
                    native=machine.uc._native.statistics())
                if console:
                    start = console.start
                    if start is None:
                        raise RuntimeError('execution stopped before the measured window')
                    window = {key: end[key] - start[key] for key in
                              ('instructions', 'batches', 'retired', 'zero_batches',
                               'polls', 'dsp_batches')}
                    window.update(cpu_seconds=end['cpu'] - start['cpu'],
                                  wall_seconds=end['wall'] - start['wall'],
                                  start_instruction=start['instructions'],
                                  mmio=counter_report(end['mmio'] - start['mmio']),
                                  io=counter_report(end['io'] - start['io']),
                                  exits=counter_report(end['exits'] - start['exits']))
                    record['window'] = window
                    record['exchange_state'] = machine.dsp_bridge.exchange.state
                    record['daa_operation'] = machine.dsp_bridge.daa.operation
                runs.append(record)
            finally:
                sip.socket.close()
                sip.rtp_socket.close()
    print(json.dumps(dict(platform=platform.platform(), python=sys.version,
                         workload='dial' if args.dial else 'idle', runs=runs), indent=2))
    return 0 if all(r['status'] == 'instruction-limit' for r in runs) else 1


if __name__ == '__main__':
    raise SystemExit(main())
