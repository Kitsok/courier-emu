"""Native services must hand back before externally visible events."""
import ctypes as c

import pytest

from courier_emu.worker_poll import WorkerPoll


class Cpu(c.Structure):
    _fields_ = [("regs", c.c_void_p), ("memory", c.c_void_p),
                ("memory_size", c.c_size_t), ("guard", c.c_void_p),
                ("io_events", c.c_void_p), ("io_count", c.c_uint32),
                ("mmio_events", c.c_void_p), ("mmio_count", c.c_uint32),
                ("batch_total", c.c_uint64)]


def scheduled():
    poll = WorkerPoll()
    s = poll.state
    s.armed = s.scheduled = s.dsp_active = s.exchange_present = 1
    s.elide_until = 1_000_000
    s.batch = 4096
    s.timer_poll_period = s.timer_poll_owed = 1024
    s.line_frame_instructions = 400_000
    s.panel_latch = 256
    cpu = Cpu()
    fn = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_uint64, c.c_uint32,
                    c.c_void_p)(poll.function)
    return poll, lambda now: fn(poll.context, now, 0, c.byref(cpu))


def test_services_preserve_clock_debt_and_yield_before_exchange():
    poll, run = scheduled()
    for at in (1024, 2048, 3072):
        assert run(at) == 1
    s = poll.state
    assert s.polls == 3
    assert s.exchange_ticks == s.x86_ticks == s.bridge_instructions == 3072
    assert s.timer_poll_owed == 1024
    assert run(4096) == 0
    assert s.last_service == 3072 and s.exchange_ticks == 3072


@pytest.mark.parametrize("field,value", [
    ("console_owed", 1024), ("codec_instructions", 399000),
    ("probe_last", -199000), ("elide_until", 1024),
])
def test_due_events_leave_service_uncommitted(field, value):
    poll, run = scheduled()
    poll.state.console_present = poll.state.codec_present = 1
    poll.state.console_owed = 8192
    setattr(poll.state, field, value)
    assert run(1024) == 0
    assert poll.state.polls == poll.state.last_service == 0


def test_console_and_inactive_dsp_clocks_are_independent():
    poll, run = scheduled()
    s = poll.state
    s.dsp_active = 0
    s.console_present = s.codec_present = 1
    s.console_owed = 8192
    assert run(1024) == 1
    assert s.console_owed == 7168
    assert s.codec_instructions == s.exchange_ticks == 1024
    assert s.x86_ticks == 0


def test_interactive_exchange_matches_python_services(monkeypatch):
    from pathlib import Path
    from courier_emu.codec import CodecBringUp, SiliconDaa
    from courier_emu.daa import CourierDaa
    from courier_emu.exchange import LineExchange
    from courier_emu.images import load_image
    from courier_emu.machine import CourierMachine
    from courier_emu.nvram import CourierNvram
    from courier_emu.profiles import ROOT, ANALOG403_IMAGE

    if not (ROOT / ANALOG403_IMAGE).exists():
        pytest.skip("optional captured 403 firmware is unavailable")

    class Console:
        poll_instructions = 8192
        closed = False

        def __init__(self):
            self.polls = 0
            self.output = []

        def poll(self, limit):
            self.polls += 1
            return b""

        def write(self, byte):
            self.output.append(byte)

        def show_lamps(self, line):
            pass

        def close(self):
            pass

        def summary(self):
            return {"polls": self.polls}

    machines, results = [], []
    for enabled in ("0", "1"):
        monkeypatch.setenv("COURIER_WORKER_POLL", enabled)
        machine = CourierMachine(
            load_image(ROOT / ANALOG403_IMAGE), with_dsp=True,
            nvram=CourierNvram.idsl403_lapm_fixture(), board_id=7,
            daa=CourierDaa("quiet"), exchange=LineExchange(),
            codec=CodecBringUp(SiliconDaa(1)), dsp_batch=4096,
            console=Console(), tick_source="dsp")
        results.append(machine.run(8_000_000).to_dict())
        machines.append(machine)
    slow, fast = machines
    assert fast._worker_poll.state.polls > 0
    assert slow.uc.memory == fast.uc.memory
    assert slow.uc.regs == fast.uc.regs
    assert results[0] == results[1]
