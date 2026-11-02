#!/usr/bin/env python3
"""Measure G.711 RTP reception against local UDP packets, including socket cost.

Use --root to compare an isolated older source tree; no PBX is contacted.
"""
import argparse
import array
import hashlib
import json
from pathlib import Path
import socket
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--packets', type=int, default=10000)
    parser.add_argument('--repeat', type=int, default=4)
    args = parser.parse_args()
    if args.packets <= 0 or args.repeat <= 0:
        parser.error('--packets and --repeat must be positive')
    sys.path.insert(0, args.root)
    from courier_emu.sip import SipConfig, SipSession

    results = []
    for codec in ('pcmu', 'pcma'):
        for repeat in range(args.repeat):
            session = SipSession(SipConfig(server='127.0.0.1:9', bind='127.0.0.1', codec=codec))
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
                    packet = (bytes((0x80, session.payload_type)) + bytes(10)
                              + bytes((i * 37 + 19) % 256 for i in range(160)))
                    samples = array.array('h')
                    start = time.process_time()
                    for _ in range(args.packets):
                        peer.sendto(packet, session.rtp_socket.getsockname())
                        session.poll()
                        samples.extend(session._rx_audio)
                        session._rx_audio.clear()
                    seconds = time.process_time() - start
                assert session.rtp_packets_received == args.packets
                assert len(samples) == 160 * args.packets
                results.append(dict(codec=codec, repeat=repeat, cpu_seconds=seconds,
                                    packets=session.rtp_packets_received, samples=len(samples),
                                    sha256=hashlib.sha256(samples.tobytes()).hexdigest()))
            finally:
                session.close()
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
