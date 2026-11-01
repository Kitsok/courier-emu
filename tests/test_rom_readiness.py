"""Startup input follows initialized firmware state, not instruction age."""
from types import SimpleNamespace

import pytest

from courier_emu.machine import CourierMachine
from courier_emu.rom_serial import RomSerialLayout
from courier_emu import x86_interpreter as x86
from courier_emu.timebase import COURIER_20MHZ, COURIER_25MHZ


@pytest.mark.parametrize("board", [COURIER_20MHZ, COURIER_25MHZ])
def test_rom_tick_uses_the_selected_board_clock(board):
    machine = object.__new__(CourierMachine)
    machine._rom_tick = True
    machine.timebase = board
    machine.tick_ms = 5
    period = machine.tick_period_instructions
    assert 0.005 <= period / board.instructions_per_second
    assert (period - 1) / board.instructions_per_second < 0.005
    machine.tick_ms = 0
    assert machine.tick_period_instructions == 0


def machine_and_memory():
    machine = object.__new__(CourierMachine)
    machine._rom_serial = RomSerialLayout(0x164, 0x1200, 0x1300, 0x1400,
                                         0x1500, 0x300, 0x301, 0x1600, 0x302)
    machine._rom_dte_opened = False
    machine._dsp_in_reset = False
    machine._rom_tick = True
    machine._supervisor_23 = False
    machine.uart = SimpleNamespace(receive_enabled=False)
    machine.dsp_bridge = SimpleNamespace(active=True, launched=True, error=None,
                                         boot_rom_enabled=True)
    memory = x86.Uc(0, 0, profile="186eb")
    memory.mem_map(0, len(memory.memory))
    return machine, memory


def test_recognized_receiver_needs_callbacks_vector_and_completed_boot():
    machine, memory = machine_and_memory()
    machine.instructions = 100_000_000
    assert not machine._rom_receive_ready(memory)
    layout = machine._rom_serial
    memory.mem_write(layout.callbacks, b"\x00\x13\x00\x00\x00\x14")
    assert not machine._rom_receive_ready(memory)
    memory.mem_write(48, b"\x00\x10\x00\x80")
    machine.instructions = 0
    assert machine._rom_receive_ready(memory)
    for field, value in [("active", False), ("launched", False), ("error", "failed")]:
        original = getattr(machine.dsp_bridge, field)
        setattr(machine.dsp_bridge, field, value)
        assert not machine._rom_receive_ready(memory)
        setattr(machine.dsp_bridge, field, original)
    machine._dsp_in_reset = True
    assert not machine._rom_receive_ready(memory)


def test_unknown_layout_obeys_uart_enable_without_adapter_writes():
    machine, memory = machine_and_memory()
    machine._rom_serial = None
    before = bytes(memory.memory)
    assert not machine._rom_receive_ready(memory)
    machine.uart.receive_enabled = True
    assert machine._rom_receive_ready(memory)
    assert memory.memory == before


def test_queued_commands_complete_before_the_old_startup_gate():
    from courier_emu.cli import _worker_command, build_parser
    from courier_emu.profiles import ROOT, ANALOG403_IMAGE
    import json
    import subprocess

    if not (ROOT / ANALOG403_IMAGE).exists():
        pytest.skip("optional captured 403 firmware is unavailable")
    args = build_parser().parse_args([
        "run", "--profile", "analog403", "--at", "AT", "--at", "ATI3",
        "--at", "ATZ", "--at", "AT", "--instructions", "20000000"])
    completed = subprocess.run(_worker_command(args), capture_output=True,
                               text=True, timeout=30, check=True)
    report = json.loads(completed.stdout)
    assert report["error"] is None
    assert report["serial_input_remaining"] == 0
    assert report["serial_text"].count("OK") == 4
    assert "USRobotics Courier V.Everything" in report["serial_text"]
    ready = [s for s in report["serial_trace"] if s.startswith("rom-dte: receiver ready at ")]
    assert len(ready) == 1 and int(ready[0].rsplit(" ", 1)[1]) < 20_000_000
