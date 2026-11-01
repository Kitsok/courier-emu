#!/usr/bin/env python3
"""Repeatable standalone 403 DSP/SIP CPU measurement against a loopback sink.

This measures boot plus idle or dialing, not a negotiated modem data call.
The reserved UDP endpoint consumes no external service and sends no responses.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import socket
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instructions', type=int, default=30_000_000)
    parser.add_argument('--dial', action='store_true')
    parser.add_argument('--repeat', type=int, default=3)
    args = parser.parse_args()
    if args.instructions <= 0 or args.repeat <= 0:
        parser.error('instructions and repeat must be positive')

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
            sip = SipSession(SipConfig(
                server='127.0.0.1:' + str(sink.getsockname()[1]),
                bind='127.0.0.1', advertise='127.0.0.1'))
            try:
                machine = CourierMachine(
                    image, with_dsp=True,
                    nvram=CourierNvram.idsl403_lapm_fixture(), board_id=7,
                    serial_input=b'ATDT100\r' if args.dial else b'',
                    daa=CourierDaa('quiet'), exchange=LineExchange(),
                    codec=CodecBringUp(SiliconDaa(1)), dsp_batch=4096,
                    tick_source='dsp', sip=sip)
                wall, cpu = time.perf_counter(), time.process_time()
                result = machine.run(args.instructions).to_dict()
                cpu = time.process_time() - cpu
                wall = time.perf_counter() - wall
                runs.append(dict(
                    wall_seconds=wall, cpu_seconds=cpu,
                    instructions=machine.instructions,
                    instructions_per_cpu_second=machine.instructions / cpu,
                    realtime_cpu_multiple=(machine.instructions / cpu
                                           / machine.timebase.instructions_per_second),
                    status=result['status'], scheduler=result['scheduler'],
                    memory_sha256=hashlib.sha256(machine.uc.memory).hexdigest(),
                    registers=list(machine.uc.regs),
                    native=machine.uc._native.statistics()))
            finally:
                sip.socket.close()
                sip.rtp_socket.close()
    print(json.dumps(dict(platform=platform.platform(), python=sys.version,
                         workload='dial' if args.dial else 'idle', runs=runs), indent=2))


if __name__ == '__main__':
    main()
