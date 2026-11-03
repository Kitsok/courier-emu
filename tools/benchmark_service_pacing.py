#!/usr/bin/env python3
"""Fixed-service pacing comparison; no firmware, SIP dialogs or modem calls.

The reference resumes after Python SIP polling and DeadlinePacer waiting.
The candidate finishes the same stable service inside C++. This isolates
pacing and handoff work; it excludes full Python snapshot reconstruction.
"""
import argparse
import ctypes as c
import json
from pathlib import Path
import select
import socket
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from courier_emu.ata import SipLine
from courier_emu.board_media_native import NativeBoardMedia
from courier_emu.exchange import LineExchange
from courier_emu.media_native import NativeSipSession
from courier_emu.pacing import DeadlinePacer
from courier_emu.sip import SipConfig, SipSession
from courier_emu.sip_line_native import NativeSipLine
from courier_emu.worker_poll import WorkerPoll


class Cpu(c.Structure):
    _fields_ = [('regs', c.c_void_p), ('memory', c.c_void_p), ('memory_size', c.c_size_t),
                ('guard', c.c_void_p), ('io_events', c.c_void_p), ('io_count', c.c_uint32),
                ('mmio_events', c.c_void_p), ('mmio_count', c.c_uint32), ('batch_total', c.c_uint64)]


def run(native, count, lead):
    session = NativeSipSession.adopt(SipSession(SipConfig(server='127.0.0.1:9', bind='127.0.0.1')))
    line = NativeSipLine.adopt(SipLine(session, exchange=LineExchange()))
    board = NativeBoardMedia(line, None, 4096)
    console, terminal = socket.socketpair()
    try:
        poll = WorkerPoll()
        s = poll.state
        s.armed = 1; s.scheduled = 3; s.native_media = board.handle
        s.elide_until = 1_000_000_000; s.batch = 4096
        s.timer_poll_period = s.timer_poll_owed = 1024
        s.panel_latch = 256; s.line_frame_instructions = 400000
        s.console_fd = console.fileno(); s.console_present = 1
        s.console_owed = s.console_poll_period = 1_000_000_000
        s.pacer_period = 10000
        s.pacer_wait.enabled = native; s.pacer_wait.interval = .002
        pacer = DeadlinePacer(interval=.002)
        cpu = Cpu()
        call = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_uint64, c.c_uint32, c.c_void_p)(poll.function)

        def wait(seconds):
            session.poll()
            return bool(select.select([console], [], [], seconds)[0])

        # Build, attach and load the library outside the timed window.
        start_cpu, start_wall = time.process_time(), time.monotonic()
        for index in range(count):
            total = (index+1)*1024
            line._next_frame_at = time.monotonic()+lead
            board.state.probe_last = total
            s.pacer_next = 0
            code = call(poll.context, total, 0, c.byref(cpu))
            if code == 0:
                assert not native
                pacer.service(total, 5_000_000, deadline=line._next_frame_at, wait=wait)
                s.pacer_next = pacer.next_check
                s.armed = 1
                code = call(poll.context, total, 0, c.byref(cpu))
            assert code == 1
        elapsed_cpu, elapsed_wall = time.process_time()-start_cpu, time.monotonic()-start_wall
        state = dict(polls=s.polls, last_service=s.last_service,
                     instructions=board.state.board_instructions,
                     timer_poll_owed=s.timer_poll_owed, console_owed=s.console_owed,
                     pacer_next=s.pacer_next)
        return dict(cpu_seconds=elapsed_cpu, wall_seconds=elapsed_wall, state=state,
                    waits=s.pacer_wait.waits if native else pacer.waits)
    finally:
        console.close(); terminal.close(); board.close(); line.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--services', type=int, default=200)
    parser.add_argument('--repeat', type=int, default=4)
    parser.add_argument('--lead', type=float, default=.001)
    args = parser.parse_args()
    if args.services <= 0 or args.repeat <= 0:
        parser.error('services and repeat must be positive')
    results = {'reference': [], 'native': []}
    for index in range(args.repeat):
        for native in ((False, True) if index % 2 == 0 else (True, False)):
            results['native' if native else 'reference'].append(run(native, args.services, args.lead))
    first = results['reference'][0]['state']
    assert all(row['state'] == first for rows in results.values() for row in rows)
    medians = {key: statistics.median(row['cpu_seconds'] for row in rows)
               for key, rows in results.items()}
    print(json.dumps(dict(services=args.services, lead=args.lead, repeat=args.repeat,
                          medians=medians, runs=results,
                          cpu_reduction_percent=100*(1-medians['native']/medians['reference'])), indent=2))


if __name__ == '__main__':
    main()
