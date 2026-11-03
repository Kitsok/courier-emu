#!/usr/bin/env python3
"""Measure user hardware counters around a native DSP kernel, excluding setup."""
import argparse
import csv
import ctypes
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def worker(args):
    from courier_emu.dsp import NativeC5x
    code = [0xbf09, 0x301, 0x8b89, 0x7790, 0x7780, 0x7980, 0x6000]
    if args.case == 'address':
        code = [0x7801, 0x7c01, 0x8b80] * 128 + [0x7980, 0x6000]
    if args.case == 'training':
        code = [0xbf08,0x320,0xbf0a,0x330,0xbc06,0xbf00,0xbe42,0xbf8f,0x7fff]
    complex_case=args.case in ('complex','complex-mixed')
    filter_case=args.case in ('filter','filter-saram')
    if filter_case:
        code=[0xbc06,0xbf00,0xbe42,0x8b89]
    if complex_case:
        code = [0xbc07 if args.case=='complex-mixed' else 0xbc06,0xbf00,0xbe42,0x8b89]
    if args.case in ('madd-circular', 'mads-circular'):
        opcode = 0xab90 if args.case == 'madd-circular' else 0xaa90
        code = [0xbf0f,0x330,0x8b8f,0xbb04,opcode,0x7980,0x6000]
    with NativeC5x.from_program(0x6000, struct.pack('<%dH' % len(code), *code)) as core:
        for address in range(0x2f0, 0x310):
            core.set_data(address, address ^ 0x55aa)
        core.set_pc(0x6000)
        if filter_case:
            core.host_write(7,0x30);core.host_write(0x26,0x10)
            base,pma=(0x810,0x2200) if args.case=='filter-saram' else (0x310,0x7000)
            filter_addresses=sorted(set(range(0x300,0x380))|set(range(base-8,base+24)))
            for a in filter_addresses:core.set_data(a,((a*137)^0xaaaa)&65535)
            core.load_program(struct.pack('<5H',30000,0xb9b0,0x7fff,0x8000,73),pma)
            core.step(4)
            helper=[0x081f,0xb805,0x881f,0x7804,0xbe59,0xbb04,0xaa90,
                    0xbe04,0x7805,0x7790,0x7780,0xa080,0x2f7b,0x9880,0xef00]
            header=[0xbf09,base,0xbf80,pma-5,0x881f,0x7a80,0x8aae,0x7980,0x6000]
            core.load_program(struct.pack('<15H',*helper),0x8aae)
            core.load_program(struct.pack('<9H',*header),0x6000);core.set_pc(0x6000)
        if complex_case:
            core.host_write(7,0x30);core.host_write(0x26,0x10)
            core.host_write(0x1e,args.cbcr)
            pointers=[0x340+ar*0x10 for ar in range(8)]
            if args.case=='complex-mixed':
                pointers=[0xbcc,0x9f8,0xdb6c,0xa22,0xdb96,0x2bf,0x2e9,0xbca]
                core.host_write(0x1a,0xbc0);core.host_write(0x1b,0xbdf)
                core.host_write(0x1c,0x58);core.host_write(0x1d,0x5d)
            else:
                core.host_write(0x1a,0x3e0);core.host_write(0x1b,0x3b0)
                core.host_write(0x1c,0x3f0);core.host_write(0x1d,0x3a0)
            complex_addresses=sorted(set(range(0x300,0x500)) |
                {a for p in pointers for a in range(max(0x60,p-48),min(65536,p+48))})
            for a in complex_addresses:core.set_data(a,((a*137)^0xaaaa)&65535)
            core.step(4)
            block=[]
            for ar,address in enumerate(pointers):block += [0xbf08|ar,address]
            block += [0xb929,0x8809,0xbec6,0xb95d,
                      0x6a8a,0x628e,0x747e,0x548d,0x5199,0x98aa,0x90ab,
                      0x6a8c,0x628e,0x747d,0x549d,0x508b,0x98ac,0x90a9,
                      0x7980,0xb93c]
            core.load_program(struct.pack('<%dH'%len(block),*block),0xb93c)
            core.set_pc(0xb93c)
        if args.case in ('madd-circular', 'mads-circular'):
            core.host_write(7,0x30);core.host_write(0x26,0x10)
            core.host_write(0x1e,0xef)
            core.host_write(0x1a,0x340);core.host_write(0x1b,0x300)
            core.host_write(0x1f,0x7000)
            core.load_program(struct.pack('<5H',1,3,5,7,9),0x7000)
            for a in range(0x300,0x340):core.set_data(a,(a*137)^0xaaaa)
        if args.case == 'training':
            core.host_write(7,0x30);core.host_write(0x26,0x10)
            core.host_write(0x1e,args.cbcr)
            for a in range(0x300,0x380):core.set_data(a,(a*137)^0xaaaa)
            core.step(6)
            block=[0x8b00,0x528a,0x8d7d,0x8c7e,0x7304,0x557e,0x8d7e,
                   0x547d,0xbe03,0x627e,0x61a0,0x6290,0x7980,0x879c]
            core.load_program(struct.pack('<14H',*block),0x879c);core.set_pc(0x879c)
        query=getattr(core.library,'courier_c5x_training_block_hits',None)
        if query:
            query.argtypes=[ctypes.c_void_p];query.restype=ctypes.c_uint64
        def hits():return int(query(core.handle)) if query else 0
        complex_query=getattr(core.library,'courier_c5x_complex_block_hits',None)
        if complex_query:
            complex_query.argtypes=[ctypes.c_void_p];complex_query.restype=ctypes.c_uint64
        def complex_hits():return int(complex_query(core.handle)) if complex_query else 0
        filter_query=getattr(core.library,'courier_c5x_filter_block_hits',None)
        if filter_query:
            filter_query.argtypes=[ctypes.c_void_p];filter_query.restype=ctypes.c_uint64
        def filter_hits():return int(filter_query(core.handle)) if filter_query else 0
        core.step_cycles(100000)
        before_hits=hits()
        before_complex_hits=complex_hits()
        before_filter_hits=filter_hits()
        with open(args.folder / 'control', 'w', buffering=1) as control, open(args.folder / 'ack') as ack:
            def command(value):
                control.write(value + '\n')
                if ack.readline().strip('\x00\r\n ') != 'ack':
                    raise RuntimeError('perf did not acknowledge phase control')
            command('enable')
            start = time.process_time()
            try:
                retired, executed_cycles = core.step_cycles(args.cycles)
                elapsed = time.process_time() - start
            finally:
                command('disable')
        addresses=(filter_addresses if filter_case else
                   complex_addresses if complex_case else
                   range(0x300,0x380) if args.case=='training' else
                   range(0x300,0x340) if args.case in ('madd-circular','mads-circular')
                   else range(0x2f0,0x310))
        state = [core.state(), core.serial_state(), core.memory_map(),
                 [core.data(a) for a in addresses],
                 [core.data_write_count(a) for a in addresses]]
        if complex_case:state.append([core.register(a) for a in range(9,0x20)])
        if filter_case:state += [[core.register(a) for a in range(9,0x20)],
                                core.stack(),core.data_write_count(0x1f)]
        (args.folder / 'kernel.json').write_text(json.dumps(dict(
            cpu_seconds=elapsed, block_hits=hits()-before_hits,
            complex_block_hits=complex_hits()-before_complex_hits,
            filter_block_hits=filter_hits()-before_filter_hits,
            retired_instructions=retired, executed_cycles=executed_cycles,
            sha256=hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--case', choices=['dmov', 'address', 'training', 'complex', 'complex-mixed',
                                         'madd-circular', 'mads-circular',
                                         'filter', 'filter-saram'], default='dmov')
    parser.add_argument('--cycles', type=int, default=1000000)
    parser.add_argument('--cbcr', type=lambda v:int(v,0), default=0,
                        help='circular-buffer configuration for training/complex cases')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--folder', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.cycles <= 0 or not 0 <= args.cbcr <= 65535:
        parser.error('cycles must be positive and cbcr must fit in 16 bits')
    os.environ['COURIER_C5X_LIBRARY'] = str(args.library.resolve())
    if args.worker:
        return worker(args)
    with tempfile.TemporaryDirectory(prefix='courier-perf-') as directory:
        folder = Path(directory)
        for name in ('control', 'ack'):
            os.mkfifo(folder / name)
        command = ['perf', 'stat', '-x,', '-e', 'cycles:u,instructions:u', '-D', '-1',
                   '--control=fifo:%s,%s' % (folder / 'control', folder / 'ack'),
                   '-o', str(folder / 'stat'), '--', sys.executable, str(Path(__file__).resolve()),
                   '--worker', '--folder', str(folder), '--library', str(args.library.resolve()),
                   '--case', args.case, '--cycles', str(args.cycles), '--cbcr', str(args.cbcr)]
        subprocess.run(command, check=True, timeout=60)
        result = json.loads((folder / 'kernel.json').read_text())
        result.update(case=args.case, modeled_cycles=args.cycles,
                      cbcr=0xef if args.case in ('madd-circular','mads-circular') else args.cbcr,
                      measurement_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      library_sha256=hashlib.sha256(args.library.read_bytes()).hexdigest(),
                      perf_csv=(folder / 'stat').read_text())
        counters = {}
        for row in csv.reader(result['perf_csv'].splitlines()):
            if len(row) >= 3 and row[2] in ('cycles:u', 'instructions:u'):
                if len(row) < 5 or float(row[4]) < 99.0:
                    raise RuntimeError('hardware counters were significantly multiplexed')
                counters[row[2]] = int(row[0].strip())
        if len(counters) != 2:
            raise RuntimeError('hardware counter results are missing or unsupported')
        result['counters'] = counters
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
