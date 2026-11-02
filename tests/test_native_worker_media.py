"""Native worker service ordering with controlled codec devices; no calls."""
import socket
import time

from test_native_board_media import pair, advance, compare
from test_worker_deadlines import scheduled


def worker(native, device, *, dsp=True):
    poll, run = scheduled()
    s = poll.state
    s.scheduled = 3;s.core = device.handle;s.native_media = native.handle
    s.batch = 64;s.dsp_active = dsp
    s.timer_poll_period = s.timer_poll_owed = 64
    s.host_port = 0x58
    return poll, run


def steady(bridge, native):
    for exchange in (bridge.exchange, native.line.exchange):
        exchange.state = 'connected';exchange.off_hook = True
    for daa in (bridge.daa, native.daa):
        daa.operation = 'dialing';daa.line_state = 'quiet';daa.qualified_samples = 4000


def test_worker_keeps_complete_steady_frames_native_without_snapshots(pair):
    bridge, native, cores = pair
    steady(bridge, native)
    for device in cores:advance(device, 760, 2880000, 0x1200)
    bridge._instructions = 64;bridge._service_exchange()
    poll, run = worker(native, cores[1])
    poll.state.debt = 12345
    poll.state.x86_ticks = poll.state.exchange_ticks = 9000
    poll.state.bridge_instructions = 88888
    poll.state.line_buffer_count = 999
    poll.state.line_buffer[0] = 321
    assert run(64) == 1
    assert poll.state.dsp_batches == 1
    assert native.state.board_instructions == 64
    assert poll.state.debt == 12345
    assert poll.state.bridge_instructions == 88888
    assert poll.state.native_media_services == 1
    assert poll.state.native_media_yields == 0
    assert poll.state.line_calls == 0
    assert (poll.state.line_buffer_count, poll.state.line_buffer[0]) == (999, 321)
    assert native.state.frames == 1
    compare(bridge, native, cores)


def test_worker_accepts_clock_edges_inside_an_undrained_transmit_batch(pair):
    bridge, native, cores = pair
    steady(bridge, native)
    for device in cores:
        advance(device, 380, 2880000, 0x1200)
        advance(device, 520, 3840000, 0x2400)
    bridge._instructions = 64;bridge._service_exchange()
    poll, run = worker(native, cores[1])
    assert run(64) == 1
    assert native.state.crossing_retune == 1
    compare(bridge, native, cores)


def test_sip_readiness_yields_before_dsp_and_resumes_exactly_one_frame(pair, monkeypatch):
    bridge, native, cores = pair
    steady(bridge, native)
    session = native.line.sip
    calls = []

    def consume():
        session.socket.recvfrom(256);calls.append(1)

    monkeypatch.setattr(session, 'poll', consume)
    for device in cores:advance(device, 760, 2880000, 0x1200)
    bridge._instructions = 64;bridge._service_exchange()
    poll, run = worker(native, cores[1])
    cycles = cores[1].state()['cycles']
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
        peer.sendto(b'ready', session.socket.getsockname())
        assert run(64) == 6
        assert native.state.x86_ticks == 64
        assert native.state.exchange_ticks == 0
        assert poll.state.timer_poll_owed == 64
        assert poll.state.dsp_batches == 0
        assert native.state.frames == 0
        native.resume(cores[1])
    assert calls == [1]
    assert native.state.frames == 1
    assert cores[1].state()['cycles'] == cycles
    compare(bridge, native, cores)


def test_detector_qualification_edge_yields_before_asic_and_dsp_tail(pair):
    bridge, native, cores = pair
    steady(bridge, native)
    bridge.daa.qualified_samples = native.daa.qualified_samples = 3200
    for device in cores:advance(device, 760, 2880000, 0x1200)
    bridge._instructions = 64;bridge._service_exchange()
    poll, run = worker(native, cores[1])
    assert run(64) == 6
    assert poll.state.dsp_batches == 0
    assert poll.state.native_media_yields == 1
    assert native.daa.detector_qualified
    assert native.state.frames == 1
    native.resume(cores[1])
    assert native.state.frames == 1
    compare(bridge, native, cores)


def test_native_pacing_uses_live_media_clock_and_buffer(pair):
    bridge, native, cores = pair
    poll, run = worker(native, cores[1], dsp=False)
    s = poll.state
    s.pacer_period = 1;s.pacer_next = 64
    s.pacer_origin = time.monotonic()+100
    s.line_buffer_count = 999;s.line_rate = 8000
    port = native.line._native_state
    port.clock_started = 1;port.frame_duration = .1
    port.next_frame_at = time.monotonic()-1
    assert run(64) == 1
    s.pacer_origin = time.monotonic()-100
    port.next_frame_at = time.monotonic()+2
    assert run(128) == 0
    assert s.last_service == 64 and s.polls == 1
