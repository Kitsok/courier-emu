#!/usr/bin/env python3
"""Fixed-work DSP delay-line/MAC kernels with exact reference/candidate checks.

These kernels exercise measured training instructions, not a full call.
Each repetition uses fresh cores and compares architectural state, serial
state, memory-map counters, operands and write counts outside the timer.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def words(values):
    return struct.pack('<%dH' % len(values), *values)


def measure(cycles):
    from courier_emu.dsp import NativeC5x
    cases = {'madd_daram': (0xab90, 0x3ff), 'madd_saram': (0xab90, 0x8ff),
             'macd_daram': (0xa390, 0x3ff), 'dmov_daram': (0x7790, 0x3ff),
             'ltd_saram': (0x7290, 0x8ff), 'madd_external': (0xab90, 0x81ff),
             'mads_control': (0xaa90, 0x3ff), 'primary_control': (None, 0x3ff)}
    results = {}
    for name, (opcode, dma) in cases.items():
        taps, pma = 162, 0x7000
        code = [0xbf09, dma, 0x8b89, 0xbba1, opcode]
        if opcode == 0xa390:
            code.append(pma)
        code += [0x7980, 0x6000]
        if opcode is None:
            code = [0x7801]*65536
        with NativeC5x.from_program(0 if opcode is None else 0x6000, words(code)) as core:
            core.host_write(7, 0x30)
            core.host_write(0x1f, pma)
            if opcode is not None:
                core.load_program(words([((k*13)^0x33cc) & 65535 for k in range(taps)]), pma)
                for k in range(taps):core.set_data(dma-k, ((k*71)^0xaa55) & 65535)
                core.set_pc(0x6000)
            core.step_cycles(10000)
            start = time.process_time()
            core.step_cycles(cycles)
            elapsed = time.process_time()-start
            snapshot = dict(state=core.state(), serial=core.serial_state(), memory_map=core.memory_map(),
                operands=[core.data(dma-k) for k in range(-1, taps)],
                writes=[core.data_write_count(dma-k) for k in range(-1, taps)])
            digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
            results[name] = dict(cpu_seconds=elapsed, sha256=digest,
                                 instructions=snapshot['state']['instructions'],
                                 cycles=snapshot['state']['cycles'])
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--cycles', type=int, default=2000000)
    parser.add_argument('--repeat', type=int, default=4)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.cycles <= 0 or args.repeat <= 0:
        parser.error('cycles and repeat must be positive')
    if args.worker:
        print(json.dumps(measure(args.cycles)))
        return
    if args.reference is None or args.candidate is None:
        parser.error('--reference and --candidate are required')
    results = {'reference': [], 'candidate': []}
    libraries = {'reference': str(args.reference.resolve()), 'candidate': str(args.candidate.resolve())}
    for index in range(args.repeat):
        for name in (('reference', 'candidate') if index % 2 == 0 else ('candidate', 'reference')):
            env = dict(os.environ, COURIER_C5X_LIBRARY=libraries[name])
            data = subprocess.check_output([sys.executable, str(Path(__file__).resolve()),
                                            '--worker', '--cycles', str(args.cycles)], env=env)
            results[name].append(json.loads(data))
    summary = {}
    for case in results['reference'][0]:
        assert len({row[case]['sha256'] for group in results.values() for row in group}) == 1, case
        medians = {name: statistics.median(row[case]['cpu_seconds'] for row in group)
                   for name, group in results.items()}
        summary[case] = dict(medians, cpu_reduction_percent=100*(1-medians['candidate']/medians['reference']))
    print(json.dumps(dict(cycles=args.cycles, repeat=args.repeat, libraries=libraries,
                          summary=summary, runs=results), indent=2))


if __name__ == '__main__':
    main()
