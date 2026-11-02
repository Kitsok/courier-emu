#!/usr/bin/env python3
"""Compare native terminal/pacing no-work checks against a loopback SIP sink.

This includes boot and dialing, not an answered call. A past media origin
forces catch-up without host-dependent sleeps; no external modem is called.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--order', default='0,1,1,0', help='comma-separated off/on switches')
    parser.add_argument('--warmup', action='store_true', help='prepend one discarded off run')
    args = parser.parse_args()
    order = args.order.split(',')
    if any(value not in ('0', '1') for value in order):
        parser.error('--order accepts only 0 and 1')
    sys.path.insert(0, args.root)
    from courier_emu.codec import CodecBringUp, SiliconDaa
    from courier_emu.console import SerialConsole
    from courier_emu.daa import CourierDaa
    from courier_emu.exchange import LineExchange
    from courier_emu.images import load_image
    from courier_emu.machine import CourierMachine
    from courier_emu.nvram import CourierNvram
    from courier_emu.profiles import ROOT, ANALOG403_IMAGE
    from courier_emu.sip import SipConfig, SipSession

    reference = None
    if args.warmup:
        order.insert(0, '0')
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sink:
        sink.bind(('127.0.0.1', 0))
        for index, enabled in enumerate(order):
            os.environ['COURIER_NATIVE_IDLE_CHECKS'] = enabled
            terminal, transport = socket.socketpair()
            console = SerialConsole(transport.detach())
            sip = SipSession(SipConfig(server='127.0.0.1:'+str(sink.getsockname()[1]),
                                       bind='127.0.0.1', advertise='127.0.0.1'))
            try:
                nvram = CourierNvram.idsl403_lapm_fixture()
                fixture_sha256 = hashlib.sha256(nvram.data).hexdigest()
                machine = CourierMachine(
                    load_image(ROOT / ANALOG403_IMAGE), with_dsp=True, nvram=nvram,
                    board_id=7, daa=CourierDaa('quiet'), exchange=LineExchange(),
                    codec=CodecBringUp(SiliconDaa(1)), dsp_batch=4096,
                    tick_source='dsp', sip=sip, console=console,
                    serial_input_schedule=[(15_000_000, b'ATDT100\r')])
                machine.dsp_bridge._sip_line._next_frame_at = 0.0
                wall, cpu = time.monotonic(), time.process_time()
                result = machine.run(40_000_000)
                cpu, wall = time.process_time() - cpu, time.monotonic() - wall
                result = result.to_dict()
                state = dict(memory_sha256=hashlib.sha256(machine.uc.memory).hexdigest(),
                             registers=list(machine.uc.regs), timers=machine.timers.status(),
                             dsp=result['dsp_bridge']['dsp'], serial=result['dsp_bridge']['serial_port'],
                             exchange=result['dsp_bridge']['exchange'])
                assert result['status'] == 'instruction-limit', result['error']
                if reference is None:
                    reference = state
                else:
                    assert state == reference, 'guest or device state diverged'
                print(json.dumps(dict(index=index, enabled=enabled,
                                      warmup=args.warmup and index == 0,
                                      fixture_sha256=fixture_sha256,
                                      cpu_seconds=cpu, wall_seconds=wall,
                                      status=result['status'], instructions=result['instructions'],
                                      scheduler=result['scheduler'], **state)), flush=True)
            finally:
                console.close()
                terminal.close()
                sip.close()


if __name__ == '__main__':
    main()
