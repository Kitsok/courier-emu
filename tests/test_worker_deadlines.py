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
    poll.cpu = cpu
    fn = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_uint64, c.c_uint32,
                    c.c_void_p)(poll.function)
    return poll, lambda now, flags=0: fn(poll.context, now, flags, c.byref(cpu))


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


@pytest.mark.parametrize("watched", [False, True])
def test_frame_interrupt_entry_respects_stack_guards(watched):
    poll, run = scheduled()
    regs = (c.c_uint32 * 14)()
    memory = (c.c_uint8 * 0x100000)()
    guard = (c.c_uint8 * 0x100000)(*([3] * 0x100000))
    regs[4], regs[9], regs[12], regs[13] = 0x800, 0x1234, 0x5678, 0x202
    memory[48:52] = [0x00, 0x01, 0x00, 0x80]
    poll.cpu.regs, poll.cpu.memory, poll.cpu.guard = map(c.addressof, (regs, memory, guard))
    poll.cpu.memory_size = len(memory)
    s = poll.state
    s.int0_ok = 1
    s.frame_instructions = 1000
    if watched:
        guard[0x7fe] |= 32
        assert run(1024, 0x202) == 0
        assert regs[4] == 0x800 and s.polls == 0
    else:
        assert run(1024, 0x202) == 1
        assert list(memory[0x7fa:0x800]) == [0x78, 0x56, 0x34, 0x12, 0x02, 0x02]
        assert (regs[4], regs[9], regs[12], regs[13]) == (0x7fa, 0x8000, 0x100, 2)
        assert s.int0_in_service and s.stack_depth == 1 and s.stack[0] == 12


def tick_scheduled():
    poll, run = scheduled()
    regs = (c.c_uint32 * 14)()
    memory = (c.c_uint8 * 0x100000)()
    guard = (c.c_uint8 * 0x100000)()
    c.memset(guard, 3, len(guard))
    regs[4], regs[9], regs[12], regs[13] = 0x800, 0x1234, 0x5678, 0x302
    memory[48:52], memory[60:64] = [0, 1, 0, 0x80], [0, 2, 0, 0x80]
    poll.cpu.regs, poll.cpu.memory, poll.cpu.guard = map(c.addressof, (regs, memory, guard))
    poll.cpu.memory_size = len(memory)
    poll.state.dsp_active = poll.state.exchange_present = 0
    poll.state.tick_period, poll.state.tick_vector = 1024, 15
    return poll, run, regs, memory, guard


@pytest.mark.parametrize("frame", [False, True])
@pytest.mark.parametrize("int1", [False, True])
def test_native_tick_preserves_frame_and_int1_priority(frame, int1):
    poll, run, regs, memory, guard = tick_scheduled()
    s = poll.state
    s.int0_ok, s.int1_enabled = frame, int1
    s.frame_instructions = 1000
    assert run(1024, 0x302) == 1
    assert (regs[4], regs[9], regs[12], regs[13]) == (0x7fa, 0x8000, 0x200, 0x102)
    assert list(memory[0x7fa:0x800]) == [0x78, 0x56, 0x34, 0x12, 0x02, 0x03]
    assert s.last_tick == s.last_service == 1024
    assert s.ticks == s.native_ticks == 1
    assert s.stack_depth == 1 and s.stack[0] == 15
    assert s.int0_pending == (12 if frame else 0)
    assert s.int1_pending == (13 if int1 else 0)
    assert not s.int0_in_service
    if frame:
        assert s.last_frame == 1000
    if frame or int1:
        assert run(2048, 0x102) == 0
        assert s.last_service == 1024  # Pending work leaves the next service to Python.


@pytest.mark.parametrize("watched", ['vector', 'stack'])
def test_native_tick_declines_guarded_entry_before_advancing_clocks(watched):
    poll, run, regs, memory, guard = tick_scheduled()
    guard[60 if watched == 'vector' else 0x7fa] |= 16 if watched == 'vector' else 32
    before = list(regs), bytes(memory)
    assert run(1024, 0x302) == 0
    assert (list(regs), bytes(memory)) == before
    assert poll.state.polls == poll.state.last_service == poll.state.ticks == 0


def test_native_tick_waits_for_if_and_does_not_underflow_a_future_origin():
    poll, run, regs, memory, guard = tick_scheduled()
    assert run(1024, 0x102) == 1
    assert poll.state.ticks == 0
    assert run(2048, 0x302) == 1
    assert poll.state.last_tick == 2048 and poll.state.ticks == 1
    poll, run, regs, memory, guard = tick_scheduled()
    poll.state.last_tick = 4096
    assert run(1024, 0x302) == 1
    assert poll.state.ticks == 0


@pytest.mark.parametrize("tick_first", [False, True])
def test_native_pending_interrupts_wait_for_if_and_keep_priority(tick_first):
    poll, run, regs, memory, guard = tick_scheduled()
    s = poll.state
    s.pending_native = 1
    s.int0_pending, s.int1_pending = 12, 13
    s.tick_period = 1024 if tick_first else 0
    memory[52:56] = [0, 3, 0, 0x80]
    assert run(1024, 0x102) == 1
    assert s.stack_depth == 0 and s.int0_pending == 12 and s.int1_pending == 13
    if tick_first:
        assert run(2048, 0x302) == 1
        assert s.stack_depth == 1 and s.stack[0] == 15
        assert s.int0_pending == 12 and s.int1_pending == 13
        assert s.native_pending_irqs == 0
        s.tick_period = 0
    at = 3072 if tick_first else 2048
    assert run(at, 0x302) == 1
    assert regs[12] == 0x100 and s.int0_in_service
    assert s.int0_pending == 0 and s.int1_pending == 13
    assert s.native_pending_irqs == 1
    assert run(at + 1024, 0x302) == 1
    assert regs[12] == 0x300 and s.int1_pending == 0
    assert s.native_pending_irqs == 2


@pytest.mark.parametrize("watched", ['vector', 'stack'])
def test_native_pending_interrupt_entry_rolls_back_before_service(watched):
    poll, run, regs, memory, guard = tick_scheduled()
    s = poll.state
    s.pending_native, s.int1_pending, s.tick_period = 1, 13, 0
    guard[52 if watched == 'vector' else 0x7fa] |= 16 if watched == 'vector' else 32
    before = list(regs), bytes(memory)
    assert run(1024, 0x302) == 0
    assert (list(regs), bytes(memory)) == before
    assert s.polls == s.last_service == s.native_pending_irqs == 0
    assert s.int1_pending == 13


def test_pending_interrupt_waits_for_the_timer_poll_boundary():
    poll, run, regs, memory, guard = tick_scheduled()
    s = poll.state
    s.pending_native, s.int1_pending, s.tick_period = 1, 13, 0
    s.timer_poll_owed = 4096
    memory[52:56] = [0, 3, 0, 0x80]
    for at in (1024, 2048, 3072):
        assert run(at, 0x302) == 1
        assert s.stack_depth == 0 and s.int1_pending == 13
    assert run(4096, 0x302) == 1
    assert s.stack_depth == 1 and s.int1_pending == 0


def test_new_frame_edge_precedes_deferred_int1():
    poll, run, regs, memory, guard = tick_scheduled()
    s = poll.state
    s.pending_native, s.int1_pending, s.tick_period = 1, 13, 0
    s.int0_ok, s.frame_instructions = 1, 1000
    memory[52:56] = [0, 3, 0, 0x80]
    assert run(1024, 0x302) == 1
    assert regs[12] == 0x100 and s.int0_in_service and s.int1_pending == 13
    assert run(2048, 0x302) == 1
    assert regs[12] == 0x300 and s.int1_pending == 0


@pytest.mark.parametrize("serial_input", [b"", b"AT\rATI7\r", b"ATDT100\r", b"AT\rATZ\rAT\r"])
def test_interactive_exchange_matches_python_services(monkeypatch, serial_input):
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
            self.owner = None
            self.previous_large = False
            self.last_native_polls = 0
            self.native_polls_with_large_buffers = 0
            self.last_dsp_batches = 0
            self.native_dialing_batches = 0

        def poll(self, limit):
            self.polls += 1
            poll = getattr(self.owner, "_worker_poll", None)
            count = poll.state.polls if poll is not None else 0
            batches = poll.state.dsp_batches if poll is not None else 0
            bridge = self.owner.dsp_bridge
            if bridge.daa.operation == "dialing" and not bridge._v8_armed:
                self.native_dialing_batches += batches - self.last_dsp_batches
            self.last_dsp_batches = batches
            large = len(self.owner.dsp_bridge._exchange_line_buffer) > 512
            if large and self.previous_large:
                self.native_polls_with_large_buffers += count - self.last_native_polls
            self.previous_large, self.last_native_polls = large, count
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
        monkeypatch.setenv("COURIER_NATIVE_TIMERS", enabled)
        monkeypatch.setenv("COURIER_NATIVE_INTERRUPTS", enabled)
        monkeypatch.setenv("COURIER_NATIVE_WORKER_TICK", enabled)
        monkeypatch.setenv("COURIER_NATIVE_WORKER_IRQS", enabled)
        machine = CourierMachine(
            load_image(ROOT / ANALOG403_IMAGE), with_dsp=True,
            nvram=CourierNvram.idsl403_lapm_fixture(), board_id=7,
            serial_input=serial_input,
            daa=CourierDaa("quiet"), exchange=LineExchange(),
            codec=CodecBringUp(SiliconDaa(1)), dsp_batch=4096,
            console=Console(), tick_source="dsp")
        machine.console.owner = machine
        result = machine.run(30_000_000).to_dict()
        scheduler = result.pop("scheduler")
        if enabled == "1":
            assert scheduler["native_dsp_batches"] > 0
            assert scheduler["native_board_ticks"] > 0
        results.append(result)
        machines.append(machine)
    slow, fast = machines
    assert fast._worker_poll.state.polls > 0
    assert fast._worker_poll.state.dsp_batches > 0
    assert fast.console.native_polls_with_large_buffers > 0
    if serial_input == b"ATDT100\r":
        assert fast.console.native_dialing_batches > 0
    assert slow.uc.memory == fast.uc.memory
    assert slow.uc.regs == fast.uc.regs
    assert results[0] == results[1]
