#!/usr/bin/env python3
"""Compare prebuilt x86 libraries on fixed register, memory and trace workloads."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import time

CASES = {
    'register_branches': ('40489191ebfa', False, False),
    'counter_loop': ('b9ff7f4975fdebf8', False, False),
    'mixed_memory': ('4001d8a30030ebf8', False, False),
    'traced_memory': ('4001d8a30030ebf8', False, True),
    'memory_control': ('8b060030a30230ebf7', False, False),
    'prefixed_control': ('26b8010040ebf9', False, False),
    '386_control': ('40489191ebfa', True, False),
}


def load(path):
    spec = importlib.util.spec_from_file_location('_x86_native', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.run


def measure(call, case, instructions):
    hexcode, wide, traced = CASES[case]
    memory = bytearray(0x1000000 if wide else 0x100000)
    code = bytes.fromhex(hexcode)
    memory[0x1000:0x1000+len(code)] = code
    memory[0x3000:0x3002] = b'\x05\x00'
    guard = bytearray([3])*len(memory)
    regs = [0]*14
    regs[3], regs[4], regs[12], regs[13] = 3, 0xf000, 0x1000, 2
    ports, events, interrupts = bytearray(65536), bytearray(4*65536), bytearray(1024)
    trace = bytearray(4096*32) if traced else None
    optional = (None,)*10+(trace,) if traced else ()
    if traced:
        guard[0x3000:0x3002] = bytes([3 | 32 | 128])*2

    def run(count, digest=None):
        remaining = count
        while remaining:
            result = call(regs, memory, guard, ports, events, min(65536, remaining),
                          None, interrupts, *optional)
            assert result[0] and result[1] in (0, 2), result
            remaining -= result[0]
            if traced and digest is not None:
                digest.update(trace[:result[10]*32])

    run(10000)
    trace_digest = hashlib.sha256()
    start = time.process_time()
    run(instructions, trace_digest)
    elapsed = time.process_time()-start
    digest = hashlib.sha256(memory)
    digest.update(repr(regs).encode())
    digest.update(trace_digest.digest())
    return dict(cpu_seconds=elapsed, sha256=digest.hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--instructions', type=int, default=5000000)
    parser.add_argument('--repeat', type=int, default=6)
    args = parser.parse_args()
    if args.instructions <= 0 or args.repeat <= 0:
        parser.error('instructions and repeat must be positive')
    calls = {'reference': load(args.reference), 'candidate': load(args.candidate)}
    results = {case: {name: [] for name in calls} for case in CASES}
    for case in CASES:
        for index in range(args.repeat):
            for name in (('reference', 'candidate') if index % 2 == 0 else ('candidate', 'reference')):
                results[case][name].append(measure(calls[name], case, args.instructions))
    summary = {}
    for case, groups in results.items():
        assert len({row['sha256'] for rows in groups.values() for row in rows}) == 1, case
        medians = {name: statistics.median(row['cpu_seconds'] for row in rows)
                   for name, rows in groups.items()}
        summary[case] = dict(medians, cpu_reduction_percent=100*(1-medians['candidate']/medians['reference']))
    print(json.dumps(dict(instructions=args.instructions, repeat=args.repeat,
                          summary=summary, runs=results), indent=2))


if __name__ == '__main__':
    main()
