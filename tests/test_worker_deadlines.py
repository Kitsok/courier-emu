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


def timer_scheduled():
    from courier_emu.timers import TimerBlock
    from courier_emu.timers_native import NativeTimerBlock
    poll, run, regs, memory, guard = tick_scheduled()
    reference = TimerBlock(fast=False)
    reference.timers[0].control, reference.timers[0].compare_a = 0xa001, 5
    model = NativeTimerBlock(reference)
    poll.state.timer_model = model.address
    poll.state.pending_native = 1
    poll.state.tick_period = 0
    memory[32:36] = [0, 4, 0, 0x80]
    return poll, run, regs, memory, guard, reference, model


def test_native_timer_expiries_latch_while_masked_or_if_is_clear():
    poll, run, regs, memory, guard, reference, model = timer_scheduled()
    s = poll.state
    reference.tick(1024)
    assert run(1024, 0x302) == 1
    assert model == reference and list(model._pending) == [8]
    assert s.stack_depth == s.timer_delivered == 0
    for block in (reference, model):
        block.controller.masked['timer'] = False
    reference.tick(2048)
    assert run(2048, 0x102) == 1
    assert model == reference and s.stack_depth == 0
    reference.tick(3072)
    assert reference.take_interrupt() == 8
    assert run(3072, 0x302) == 1
    assert model == reference
    assert regs[12] == 0x400
    assert s.timer_delivered == s.native_timer_irqs == 1
    assert s.native_timer_polls == 3


@pytest.mark.parametrize('watched', ['vector', 'stack'])
def test_guarded_timer_expiry_does_not_commit_counter_or_request(watched):
    poll, run, regs, memory, guard, reference, model = timer_scheduled()
    model.controller.masked['timer'] = False
    guard[35 if watched == 'vector' else 0x7fa] |= 16 if watched == 'vector' else 32
    before = bytes(model.buffer), list(regs), bytes(memory)
    assert run(1024, 0x302) == 0
    assert (bytes(model.buffer), list(regs), bytes(memory)) == before
    assert poll.state.polls == poll.state.native_timer_polls == 0


def test_timer_request_suppresses_tick_generation_but_keeps_frame_int1_priority():
    poll, run, regs, memory, guard, reference, model = timer_scheduled()
    s = poll.state
    model.controller.masked['timer'] = False
    model.controller.masked['int1'] = False
    s.tick_period, s.int0_ok, s.frame_instructions = 1024, 1, 1000
    s.int1_pending = 13
    memory[52:56] = [0, 3, 0, 0x80]
    assert run(1024, 0x302) == 1
    assert regs[12] == 0x100
    assert (s.int0_pending, s.int1_pending, s.timer_pending) == (0, 13, 8)
    assert model.interrupts == 1 and s.timer_delivered == 0
    assert s.ticks == 0
    model.timers[0].control &= ~0x8000
    for at, offset in ((2048, 0x300), (3072, 0x400), (4096, 0x200)):
        assert run(at, 0x302) == 1
        assert regs[12] == offset
    assert s.timer_delivered == s.native_timer_irqs == 1
    assert s.timer_pending == 0 and model.interrupts == 1


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
        monkeypatch.setenv("COURIER_NATIVE_TIMER_MODEL", enabled)
        monkeypatch.setenv("COURIER_NATIVE_TIMER_POLL", enabled)
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
            assert scheduler["native_timer_polls"] > 0
            assert scheduler["native_timer_irqs"] > 0
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


@pytest.mark.parametrize('event', ['input', 'eof', 'badfd'])
def test_native_empty_console_poll_preserves_phase_and_yields_for_events(event):
    import socket
    poll, run = scheduled()
    s = poll.state
    s.dsp_active = s.exchange_present = 0
    s.console_present = 1
    s.console_owed = 1024
    s.console_poll_period = 8192
    peer, worker = socket.socketpair()
    try:
        s.console_fd = worker.fileno()
        assert run(1024) == 1
        assert s.console_owed == 8192
        assert s.native_console_polls == 1
        for now in range(2048, 9216, 1024):
            assert run(now) == 1
        if event == 'input':
            peer.sendall(b'AT\r')
        elif event == 'eof':
            peer.close()
        else:
            worker.close()
        before = (s.last_service, s.console_owed, s.native_console_polls)
        assert run(9216) == 0
        assert (s.last_service, s.console_owed, s.native_console_polls) == before
        if event == 'input':
            assert worker.recv(16) == b'AT\r'  # Readiness never consumes input.
    finally:
        peer.close()
        worker.close()


@pytest.mark.parametrize('buffered,future', [(0, False), (0, True), (8000000, True)])
def test_native_pacer_only_commits_checks_without_positive_lead(buffered, future):
    import time
    poll, run = scheduled()
    s = poll.state
    s.dsp_active = s.exchange_present = 0
    s.line_rate = 8000
    s.line_buffer_count = buffered
    s.pacer_origin = time.monotonic() + (60 if future and not buffered else -60)
    s.pacer_next = s.pacer_period = 1024
    if future:
        assert run(1024) == 0
        assert s.last_service == s.native_pacer_checks == 0
        assert s.pacer_next == 1024
    else:
        assert run(1024) == 1
        assert s.native_pacer_checks == 1 and s.pacer_next == 2048


def test_firmware_with_plain_console_matches_python_idle_checks(monkeypatch):
    import socket
    from courier_emu.codec import CodecBringUp, SiliconDaa
    from courier_emu.console import SerialConsole
    from courier_emu.daa import CourierDaa
    from courier_emu.exchange import LineExchange
    from courier_emu.images import load_image
    from courier_emu.machine import CourierMachine
    from courier_emu.nvram import CourierNvram
    from courier_emu.profiles import ROOT, ANALOG403_IMAGE
    from courier_emu.sip import SipConfig, SipSession

    machines, results = [], []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sink:
        sink.bind(('127.0.0.1', 0))
        for enabled in ('0', '1'):
            monkeypatch.setenv('COURIER_NATIVE_IDLE_CHECKS', enabled)
            terminal, transport = socket.socketpair()
            console = SerialConsole(transport.detach())
            sip = SipSession(SipConfig(server='127.0.0.1:'+str(sink.getsockname()[1]),
                                       bind='127.0.0.1', advertise='127.0.0.1'))
            try:
                machine = CourierMachine(
                    load_image(ROOT / ANALOG403_IMAGE), with_dsp=True,
                    nvram=CourierNvram.idsl403_lapm_fixture(), board_id=7,
                    daa=CourierDaa('quiet'), exchange=LineExchange(),
                    codec=CodecBringUp(SiliconDaa(1)), dsp_batch=4096,
                    tick_source='dsp', sip=sip, console=console,
                    serial_input_schedule=[(15_000_000, b'ATDT100\r')])
                # A deliberately past media origin exercises catch-up without
                # making equivalence depend on host speed or sleep jitter.
                machine.dsp_bridge._sip_line._next_frame_at = 0.0
                result = machine.run(40_000_000).to_dict()
                assert result['status'] == 'instruction-limit', (result['status'], result['error'], result['instructions'])
                if enabled == '1':
                    state = machine._worker_poll.state
                    assert state.native_console_polls > 0
                    assert state.native_pacer_checks > 0
                machines.append(machine)
                results.append(result)
            finally:
                console.close()
                terminal.close()
                sip.close()
    a, b = machines
    assert a.uc.memory == b.uc.memory
    assert a.uc.regs == b.uc.regs
    assert a.timers.status() == b.timers.status()
    for key in ('serial_text', 'serial_input_remaining', 'ticks', 'timer_interrupts'):
        assert results[0][key] == results[1][key]
    for key in ('dsp', 'serial_port', 'exchange', 'line_service', 'core_codec'):
        assert results[0]['dsp_bridge'][key] == results[1]['dsp_bridge'][key]
    assert results[1]['dsp_bridge']['exchange']['dialed'] == '100'


def test_shared_machine_service_phases_ignore_legacy_snapshots():
    from courier_emu.service_native import ServiceState
    poll, run = scheduled()
    live = ServiceState(4096, 2048, 100, 200, 3)
    s = poll.state
    s.service_model = c.addressof(live)
    s.console_present = 1
    s.console_owed = 9999;s.timer_poll_owed = 8888
    s.last_frame = 7777;s.last_tick = 6666;s.ticks = 5555
    assert run(1024) == 1
    assert (live.console_owed, live.timer_poll_owed) == (3072, 1024)
    assert (live.last_frame, live.last_tick, live.ticks) == (100, 200, 3)
    assert (s.console_owed, s.timer_poll_owed, s.last_frame, s.last_tick, s.ticks) == (
        9999, 8888, 7777, 6666, 5555)
