"""MAME 80186 CPU adapter for the Courier board model.

All instruction decoding/execution runs in MAME. The Python superclass supplies
the existing register, memory and hook API; its instruction interpreter is
never called. Board services retain their current instruction-clock schedule.
"""
from collections import Counter
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile

from .build import packaged_library, require_build_allowed
from . import x86_interpreter as x86

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / 'native/vendor/mame186'
LIBRARY = ROOT / '.build' / ('_mame_native' + sysconfig.get_config_var('EXT_SUFFIX'))


def build_library():
    installed = packaged_library(LIBRARY.name)
    if installed is not None:
        return installed
    sources = [ROOT / 'native/mame_adapter.cpp', VENDOR / 'cpu/i86.cpp',
               VENDOR / 'cpu/i186.cpp', VENDOR / 'shim/emu.cpp']
    dependencies = sources + list(VENDOR.rglob('*.h')) + [
        ROOT / 'native/interrupts186.hpp', ROOT / 'native/serial186.hpp', ROOT / 'native/timers186.hpp',
        ROOT / 'native/microwire93c66.hpp', ROOT / 'native/dte186.hpp',
        ROOT / 'native/dte_transmit.hpp', ROOT / 'native/terminal_io.hpp']
    if not LIBRARY.exists() or any(p.stat().st_mtime_ns > LIBRARY.stat().st_mtime_ns
                                   for p in dependencies):
        require_build_allowed(LIBRARY)
        LIBRARY.parent.mkdir(exist_ok=True)
        fd, name = tempfile.mkstemp(dir=LIBRARY.parent, suffix=LIBRARY.suffix)
        os.close(fd)
        try:
            subprocess.run(['c++', '-std=c++20', '-O2', '-Wall', '-Wextra',
                            '-Wno-unused-parameter', '-Wno-unused-variable',
                            *(['-bundle', '-undefined', 'dynamic_lookup'] if sys.platform == 'darwin'
                              else ['-shared', '-fPIC']),
                            '-I', sysconfig.get_path('include'), '-I', str(VENDOR / 'shim'),
                            '-I', str(VENDOR / 'cpu'), *(str(p) for p in sources), '-o', name],
                           check=True, capture_output=True)
            os.replace(name, LIBRARY)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    return LIBRARY


def load_library():
    spec = importlib.util.spec_from_file_location('_mame_native', build_library())
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MameUc(x86.Uc):
    def __init__(self, arch, mode, *, profile='186eb'):
        if profile != '186eb':
            raise ValueError('the MAME backend supports only the 186eb board')
        super().__init__(arch, mode, profile=profile)
        # Keep the custom CPU decoder/trace-buffer ABI disabled. Shared native
        # devices and board-worker callbacks are enabled independently.
        self.native_enabled = False
        module = load_library()
        self._mame_run = module.run
        self._mame_configure = module.configure
        self._mame_handle = module.create()
        self.memory, self._mame_guard, registers = module.buffers(self._mame_handle)
        self.regs = memoryview(registers).cast('I')
        self._mame_bindings_key = None
        self._mame_signature = None
        self._mame_base = 0
        self.mame_retired = 0
        self._mame_device_access = bytearray(256)
        self._mame_mmio_events = bytearray(8 * 8 * 65536)
        self._mame_nvram = self._mame_dte_line = None
        self._mame_transmitter = None
        self._mame_transfer_span = None
        self._mame_fault_buffer = bytearray(8 * 257)
        self._mame_faults = memoryview(self._mame_fault_buffer).cast('Q')
        self._mame_fault_counter = Counter()
        self._mame_services_synced = True

    def _prepare_guard(self):
        signature = (len(self.mapped), len(self.hooks), self.native_mmio_batch,
                     id(self.native_uart), id(self.native_timer_reads), id(self._mame_nvram))
        if signature == self._mame_signature:
            return
        guard = self._mame_guard
        guard[:] = bytes(len(guard))
        for first, last, perms in self.mapped:
            guard[first:last] = guard[first:last].translate(bytes(v | perms for v in range(256)))
        for hooks, bit in ((self._code_hooks, 8), (self._read_hooks, 16), (self._write_hooks, 32)):
            for _, _, first, last in hooks:
                if not last:
                    first, last = 0, len(guard) - 1
                first, last = max(0, first), min(len(guard) - 1, last)
                guard[first:last + 1] = guard[first:last + 1].translate(bytes(v | bit for v in range(256)))
        for first, last in self.native_mmio_batch:
            for address in range(first, last + 1):
                guard[address] |= 64
        self._mame_device_access[:] = bytes(256)
        if self.native_uart is not None or self.native_timer_reads is not None or self._mame_nvram is not None:
            for bit, hooks, own_hook in ((1, self._read_hooks, self.native_uart_hooks[0]),
                                         (2, self._write_hooks, self.native_uart_hooks[1])):
                for address in (0xff08, *range(0xff12, 0xff20, 2),
                                *range(0xff30, 0xff48, 2), *range(0xff50, 0xff60, 2),
                                *range(0xff60, 0xff6c, 2)):
                    if not any(callback is not own_hook
                               and (end == 0 or begin <= address + 1 and end >= address)
                               for callback, _, begin, end in hooks):
                        self._mame_device_access[address & 255] |= bit
        self._mame_signature = signature

    def _finish_native_faults(self):
        if self._mame_faults[0]:
            for vector, count in enumerate(self._mame_faults[1:]):
                if count:
                    self._mame_fault_counter[vector] += count
                    self._mame_faults[vector + 1] = 0
            self._mame_faults[0] = 0

    def _mame_event(self, kind, address, size, value, done):
        # Publish native service work before a Python device handler sees it.
        # The worker stays disarmed until the existing instruction-clock
        # callback rearms it; ordinary instructions can finish this batch.
        if not self._mame_services_synced:
            self.native_after_run()
            self._mame_services_synced = True
        self.retired = self._mame_base + done + (kind in (3, 4))
        self._finish_native_faults()
        if self._mame_transmitter is not None:
            self._mame_transmitter.finish()
        if kind in (1, 2):
            self._memory_hooks(x86.UC_HOOK_MEM_READ if kind == 1 else x86.UC_HOOK_MEM_WRITE,
                               address, size, value)
        elif kind in (3, 4):
            answer = self._io(x86.UC_X86_INS_IN if kind == 3 else x86.UC_X86_INS_OUT,
                              address, size, value) or 0
            if self.native_after_io is not None and (
                    self.native_after_io_ports is None or self.native_after_io_ports[address]):
                self.native_after_io()
            return answer | (0 if self.running else 1 << 32)
        elif kind == 5:
            before = self.regs[x86.UC_X86_REG_CS], self.regs[x86.UC_X86_REG_IP]
            for callback, user, first, last in self._code_hooks:
                if not last or first <= address <= last:
                    callback(self, address, 1, user)
            if not self.running:
                return 0
            after = self.regs[x86.UC_X86_REG_CS], self.regs[x86.UC_X86_REG_IP]
            return 2 if before != after else 1
        elif kind == 6:
            if size:
                self.fault = address
            for callback, user in self._intr_hooks:
                callback(self, address, user)
        return 1 if self.running else 1 << 32

    def emu_start(self, begin, _until, timeout=0, count=0):
        if timeout:
            raise ValueError('MAME adapter does not support a wall-clock execution timeout')
        if self._physical(self.regs[x86.UC_X86_REG_CS], self.regs[x86.UC_X86_REG_IP]) != begin:
            self.regs[x86.UC_X86_REG_IP] = (begin - self.regs[x86.UC_X86_REG_CS] * 16) & 0xffff
        self._prepare_guard()
        self.running, self.halted = True, False
        retired = 0
        while self.running and (not count or retired < count):
            self._prepare_guard()
            budget = min(1048576, count - retired) if count else 1048576
            polling = self.native_poll is not None and self._clock_callback is not None
            if self._clock_callback is not None and not polling:
                if self.retired + 1 >= self._clock_next:
                    self._clock_callback(self, self.retired + 1, self._clock_user)
                    self._clock_next = self.retired + 1 + self._clock_period
                    if not self.running:
                        break
                budget = min(budget, self._clock_next - self.retired - 1)
            if budget <= 0:
                continue
            if self.native_before_run is not None:
                self.native_before_run()
            self._mame_services_synced = self.native_after_run is None
            self._mame_base = self.retired
            host_function, host_context, host_ports = self.native_host_io or (None, None, None)
            timer_reads = self.native_timer_reads
            if timer_reads is not None:
                timer_reads.prepare(self.native_host_base + self._mame_base)
            key = (id(self.native_irq_state), id(self.native_uart),
                   id(self.native_mmio_callback), host_function, host_context, id(host_ports),
                   id(timer_reads), id(self._mame_nvram), id(self._mame_dte_line),
                   self.native_poll if polling else None, id(self._mame_transmitter),
                   self._mame_transfer_span, id(self.native_int_mode))
            if key != self._mame_bindings_key:
                bindings = (self.native_irq_state,
                        self.native_uart.buffer if self.native_uart is not None else None,
                        self._mame_device_access,
                        self._mame_mmio_events if self.native_mmio_callback is not None else None,
                        host_function, host_context, host_ports,
                        0,
                        timer_reads.model_buffer if timer_reads is not None else None,
                        self._mame_nvram._native_buffer if self._mame_nvram is not None else None,
                        self._mame_dte_line.buffer if self._mame_dte_line is not None else None,
                        self.native_poll if polling else None,
                        self._mame_transmitter.handle if self._mame_transmitter is not None else None,
                        self._mame_transfer_span, self.native_int_mode, self._mame_fault_buffer)
                self._mame_configure(self._mame_handle, bindings)
                self._mame_bindings_key = key
            try:
                done, halted, irq_fallback, mmio_count, poll_next, poll_code = self._mame_run(
                    self._mame_handle, budget, self._mame_event,
                    self.native_host_base + self._mame_base, self.retired,
                    self._clock_next, self._clock_period)
            except RuntimeError as exc:
                raise x86.UcError(str(exc)) from exc
            self.retired = self._mame_base + done
            self.mame_retired += done
            self._finish_native_faults()
            retired += done
            if not self._mame_services_synced:
                self.native_after_run()
                self._mame_services_synced = True
            if polling:
                self._clock_next = poll_next
            if self._mame_transmitter is not None:
                self._mame_transmitter.finish()
            if timer_reads is not None:
                timer_reads.finish()
            if self._mame_nvram is not None:
                self._mame_nvram.finish_reads(self.native_uart_counts)
            if self.native_uart is not None:
                self.native_uart.finish_reads(self.native_uart_counts)
            if mmio_count:
                self.native_mmio_callback(memoryview(self._mame_mmio_events), mmio_count)
            if irq_fallback:
                self._native_irq_fallback = True
                self._native_irq_guard_fallbacks += 1
                self.running = False
            self.halted = bool(halted)
            if halted:
                self.running = False
            if poll_code >= 0 and self.running:
                now = self.retired + 1
                if poll_code >= 2:
                    self.native_poll_resume(self, now, poll_code)
                else:
                    self._clock_callback(self, now, self._clock_user)
                self._clock_next = now + self._clock_period
            if not done and self.running and poll_code < 0:
                raise x86.UcError('MAME made no instruction progress')
