"""Live DTR must remain visible when native panel caching is enabled."""
from collections import deque
from types import SimpleNamespace

from courier_emu.machine import CourierMachine
from courier_emu.panel import RING_DETECT_BIT


def test_serialsim_cached_panel_tracks_dtr_and_yields_for_ringing():
    machine = CourierMachine.__new__(CourierMachine)
    machine.console = SimpleNamespace(serialsim=True, dtr=True)
    machine._terminal_connected = True
    machine._rom_serial = object()
    machine.serial_rx = deque()
    machine.port_values = {}
    machine.panel = SimpleNamespace(board_id=None)
    bridge = SimpleNamespace(line=SimpleNamespace(peer_ringing=False), exchange=None)

    high = machine._native_panel_input_14(bridge, 0xff)
    machine.console.dtr = False
    low = machine._native_panel_input_14(bridge, 0xff)
    assert high & 1
    assert not low & 1
    assert high ^ low == 1  # only DTR changes; attachment stays true
    assert low & RING_DETECT_BIT
    machine.console.dtr = True
    assert machine._native_panel_input_14(bridge, 0xff) == high

    bridge.line.peer_ringing = True
    assert machine._native_panel_input_14(bridge, 0xff) is None
    bridge.line.peer_ringing = False
    machine.port_values[0x14] = 0
    assert machine._native_panel_input_14(bridge, 0xff) is None
