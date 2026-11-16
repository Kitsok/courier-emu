"""Verify the migrated EEPROM protocol and its native parallel-port route."""
from collections import Counter

import pytest
from courier_emu.x86_mame import LIBRARY

from courier_emu.nvram import CourierNvram, BIT_CHIP_SELECT as CS, BIT_CLOCK as CLK, BIT_DATA as DI
from courier_emu.nvram_native import NativeCourierNvram


def transaction(device, opcode, address, data=None):
    def bit(value):
        value = CS | (DI if value else 0)
        device.write_latch(value)
        device.write_latch(value | CLK)

    for value in [0, 1] + [(opcode << 8 | address) >> n & 1 for n in range(9, -1, -1)]:
        bit(value)
    result = 0
    if opcode == 2:
        assert not device.read_latch() & DI  # dummy bit
        for _ in range(16):
            bit(0)
            result = result << 1 | bool(device.read_latch() & DI)
    elif data is not None:
        for n in range(15, -1, -1):
            bit(data >> n & 1)
    device.write_latch(0)
    return result


def test_native_microwire_matches_reference_read_write_and_erase_protocol():
    reference = CourierNvram()
    native = NativeCourierNvram.adopt(CourierNvram())
    operations = [(1, 0x45, 0x1234), (0, 0xc0, None), (1, 0x45, 0xabcd),
                  (2, 0x45, None), (3, 0x45, None), (2, 0x45, None),
                  (1, 0x46, 0x5678), (0, 0x80, None), (2, 0x46, None),
                  (0, 0, None), (1, 0x45, 0x1234)]
    for operation in operations:
        assert transaction(reference, *operation) == transaction(native, *operation)
        assert bytes(native.data) == bytes(reference.data)
        assert native.status() == reference.status()


@pytest.mark.skipif(not LIBRARY.exists(), reason='build the optional MAME backend first')
def test_mame_parallel_port_eeprom_clocks_avoid_python_and_retain_reset_edge():
    from courier_emu.x86_mame import MameUc
    from courier_emu import x86_interpreter as x
    from courier_emu.uart import DteTransmitLine
    from courier_emu.dte_native import NativeDteTransmitLine

    machine = MameUc(0, 0)
    machine.mem_map(0, 0x100000)
    device = NativeCourierNvram.adopt(CourierNvram())
    device.set_word(0x45, 0xabcd)
    machine._mame_nvram = device
    machine._mame_dte_line = NativeDteTransmitLine(DteTransmitLine(17))
    machine.native_uart_counts = Counter()
    machine.native_mmio_callback = lambda *_: None
    machine.mem_write(0xff56, b'\x8a\x00')
    calls = []

    def read(*_):
        raise AssertionError('EEPROM read left native bus')

    def write(_owner, _access, address, _size, value, _user):
        calls.append((address, value))

    machine.hook_add(x.UC_HOOK_MEM_READ, read, None, 0xff50, 0xff5f)
    machine.hook_add(x.UC_HOOK_MEM_WRITE, write, None, 0xff50, 0xff5f)
    machine.native_uart_hooks = (read, write)
    code = bytearray()
    count = 0

    def word(address, value):
        nonlocal count
        code.extend(b'\xc7\x06' + address.to_bytes(2, 'little') + value.to_bytes(2, 'little'))
        count += 1

    for bit in [0, 1] + [(0x245 >> n) & 1 for n in range(9, -1, -1)]:
        word(0xff5e, bit << 7)
        word(0xff56, 0xaa)
        word(0xff56, 0xae)
    for i in range(16):
        word(0xff56, 0xaa)
        word(0xff56, 0xae)
        code.extend(b'\xa0\x5a\xff\xa2' + (0x2000 + i).to_bytes(2, 'little'))
        count += 2
    word(0xff56, 0x8a)
    word(0xff56, 0x88)  # actual DSP reset transition must reach board wiring
    machine.mem_write(0x1000, code)
    machine.emu_start(0x1000, 0, count=count)
    sampled = bytes(machine.mem_read(0x2000, 16))
    assert sum(((value >> 7) & 1) << (15 - i) for i, value in enumerate(sampled)) == 0xabcd
    assert calls == [(0xff56, 0x88)]
    assert device.reads == 1
