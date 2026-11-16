"""Opt-in, read-only snapshots of the ROM DTE receive path."""
from __future__ import annotations

import json
from pathlib import Path
import re
import time


class DteReceiveProbe:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.write_text('')
        self.next_sample = 0.0
        self.origin = time.monotonic()

    def sample(self, machine, cpu, *, final=False):
        now = time.monotonic()
        if not final and now < self.next_sample:
            return
        self.next_sample = now + .1
        registers = machine._x86_const
        layout, uart = machine._rom_serial, machine.uart
        flags = cpu.reg_read(registers.UC_X86_REG_FLAGS)
        state = dict(seconds=round(now-self.origin, 6), final=final,
                     instructions=machine.instructions,
                     timer_poll_owed=machine._timer_poll_owed,
                     console_poll_owed=machine._console_owed,
                     int0_in_service=machine._int0_in_service,
                     pc=(cpu.reg_read(registers.UC_X86_REG_CS) << 4)
                     + cpu.reg_read(registers.UC_X86_REG_IP),
                     interrupt_retries=getattr(cpu, '_clock_interrupt_retries', 0),
                     flags=flags, input_count=len(machine.serial_rx),
                     input_head=bytes(list(machine.serial_rx)[:8]).hex(),
                     online=machine.online_mode,
                     interrupt_stack=list(machine._interrupt_stack),
                     pending=dict(int0=machine._int0_pending, int1=machine._int1_pending,
                                  external=machine._external_interrupt_pending,
                                  timer=machine._timer_interrupt_pending),
                     controller=machine.timers.controller.status(),
                     serial_vector=bytes(cpu.mem_read(0x50, 4)).hex())
        blocked = []
        if not flags & 0x200:
            blocked.append('interrupts_disabled')
        if uart is not None:
            state['uart'] = dict(uart.status(), pending=list(uart.pending), holding=uart.holding,
                                 receive_ready=uart.receive_ready,
                                 receive_holding=uart.receive_holding)
            state['wire'] = dict(busy=machine.dte_line.busy,
                                 complete=machine.dte_line.complete(machine.instructions))
            if uart.pending:
                blocked.append('uart_pending')
            if not (uart.receive_enabled or machine._rom_tick):
                blocked.append('receiver_disabled')
        if layout is not None:
            state['callbacks'] = bytes(cpu.mem_read(layout.callbacks, 6)).hex()
            callback = int.from_bytes(cpu.mem_read(layout.callbacks, 2), 'little')
            code = bytes(cpu.mem_read(machine.image.load_base+callback, 0x40))
            # Recognize the resident RX ring writer rather than borrowing
            # another firmware image's RAM addresses.
            if code[:2] == b'\x8b\x3e' and code[4:6] == b'\x88\x05':
                consumer = re.search(rb'\xa1(..)\x3b\xc7', code, re.S)
                if consumer:
                    producer_cell = int.from_bytes(code[2:4], 'little')
                    consumer_cell = int.from_bytes(consumer[1], 'little')
                    state['receive_ring'] = dict(
                        producer_cell=producer_cell, consumer_cell=consumer_cell,
                        producer=int.from_bytes(cpu.mem_read(producer_cell, 2), 'little'),
                        consumer=int.from_bytes(cpu.mem_read(consumer_cell, 2), 'little'))
            state['mode'] = bytes(cpu.mem_read(layout.mode, 1)).hex()
            state['frontend_ready'] = machine._rom_receive_ready(cpu)
            if not state['frontend_ready']:
                blocked.append('frontend_not_ready')
        state['blocked'] = blocked
        native_state = getattr(machine, '_native_service_state', None)
        if native_state is not None:
            state['native_irq'] = dict(enabled=bool(native_state.irq_enabled),
                                       pending=native_state.pending_mask,
                                       entries=list(native_state.irq_entries),
                                       guard_fallbacks=getattr(cpu, '_native_irq_guard_fallbacks', 0))
        with self.path.open('a') as output:
            output.write(json.dumps(state, separators=(',', ':'))+'\n')
