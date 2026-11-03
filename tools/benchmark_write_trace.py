#!/usr/bin/env python3
"""Compare synchronous and buffered diagnostic RAM hooks at fixed guest work."""
import argparse
from collections import Counter, deque
import hashlib
import json
from pathlib import Path
import statistics
from struct import Struct
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from courier_emu import x86_interpreter as x86
from courier_emu.machine import MmioEvent

RECORD = Struct('=8I')


def run(buffered, instructions, unwatched=False):
    cpu = x86.Uc(0, 0, profile='186eb')
    cpu.mem_map(0, len(cpu.memory))
    # The common training sites increment/decrement words in the watch range.
    code = 'ff060030 ff0e0230 ebf6' if unwatched else 'ff06ea02 ff0eec02 ebf6'
    cpu.mem_write(0x1000, bytes.fromhex(code))
    counts, history = Counter(), deque(maxlen=1000)

    def record(address, size, value, pc):
        counts[f'pc={pc:05x} address={address:04x} size={size} value={value:0{size*2}x}'] += 1
        history.append(MmioEvent('write', address, size, value, pc))

    def observe(uc, access, address, size, value, user):
        pc = ((uc.reg_read(x86.UC_X86_REG_CS) << 4)
              + uc.reg_read(x86.UC_X86_REG_IP)) & 0xfffff
        record(address, size, value, pc)

    def replay(events, count):
        for address, value, pc, size, *_ in RECORD.iter_unpack(events[:count*32]):
            record(address, size, value, pc)

    cpu.hook_add(x86.UC_HOOK_MEM_WRITE, observe, None, 0x02ca, 0x030f)
    if buffered:
        cpu.native_write_trace = ((0x02ca, 0x030f),)
        cpu.native_write_trace_hook = observe
        cpu.native_write_trace_callback = replay
    # Build/load the native extension and its guards outside the window.
    cpu.emu_start(0x1000, 0, count=3)
    start = time.process_time()
    cpu.emu_start(0x1000, 0, count=instructions)
    elapsed = time.process_time()-start
    digest = hashlib.sha256()
    digest.update(cpu.memory)
    digest.update(repr(cpu.regs).encode())
    digest.update(repr(sorted(counts.items())).encode())
    digest.update(repr(list(history)).encode())
    return dict(cpu_seconds=elapsed, state_sha256=digest.hexdigest(),
                records=sum(counts.values()), batches=cpu._native.batches)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instructions', type=int, default=300000)
    parser.add_argument('--repeat', type=int, default=4)
    parser.add_argument('--unwatched', action='store_true',
                        help='write outside the diagnostic range to check ordinary execution overhead')
    args = parser.parse_args()
    if args.instructions <= 0 or args.repeat <= 0:
        parser.error('instructions and repeat must be positive')
    results = {'synchronous': [], 'buffered': []}
    for i in range(args.repeat):
        for buffered in ((False, True) if i % 2 == 0 else (True, False)):
            results['buffered' if buffered else 'synchronous'].append(run(buffered, args.instructions, args.unwatched))
    assert len({r['state_sha256'] for group in results.values() for r in group}) == 1
    medians = {name: statistics.median(r['cpu_seconds'] for r in group)
               for name, group in results.items()}
    print(json.dumps(dict(instructions=args.instructions, unwatched=args.unwatched,
                          runs=results, medians=medians,
                          cpu_reduction_percent=100*(1-medians['buffered']/medians['synchronous'])), indent=2))


if __name__ == '__main__':
    main()
