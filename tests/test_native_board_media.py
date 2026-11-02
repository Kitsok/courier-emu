"""Controlled DSP/codec device scripts; no modem firmware or calls."""
from collections import deque
import struct

import pytest

from courier_emu.analog_native import NativeDaa
from courier_emu.ata import SipLine
from courier_emu.board_media_native import NativeBoardMedia
from courier_emu.bridge import CourierDspBridge, LineToCodec
from courier_emu.daa import CourierDaa
from courier_emu.dsp import NativeC5x
from courier_emu.exchange import LineExchange
from courier_emu.media_native import NativeSipSession
from courier_emu.resample import BandLimitedResampler
from courier_emu.sip import SipConfig, SipSession
from courier_emu.sip_line_native import NativeSipLine


def configure(device):
    device.configure_rom_codec();device.configure_line_frame_interrupt(5, 0xffff)
    for word in (3, 0x010a, 3, 0x0214):device.host_write(0x21, word)


def core():
    device = NativeC5x.from_program(0, struct.pack('<H', 0xbe22))
    configure(device)
    return device


def advance(device, count, mclk, value):
    device.set_codec_mclk(mclk);device.host_write(0x21, value)
    for _ in range(count):
        state = device.codec_state()
        device.step_cycles(state['line_frame_next_cycle']-state['cycles'])


def reference(device, line, daa):
    bridge = CourierDspBridge.__new__(CourierDspBridge)
    bridge.core = device;bridge._sip_line = line;bridge.exchange = line.exchange;bridge.daa = daa
    bridge.batch = 64;bridge._instructions = 0
    bridge._exchange_codec_last = bridge._exchange_idle = bridge._exchange_tx_index = 0
    bridge._exchange_line_buffer = [];bridge._exchange_rx_samples = []
    bridge._codec_to_line = BandLimitedResampler();bridge._line_to_codec = LineToCodec()
    bridge._rx_cushion_rate = None;bridge._codec_in_flight = deque();bridge._carrier_probe = deque()
    bridge._line_service = dict(tx_consumed=0, tx_index=0, tx_peak_codec=0, tx_peak_line=0)
    bridge._line_rx_peak = bridge._codec_in_peak = bridge._codec_handed_peak = 0
    bridge._codec_handed_at = bridge._codec_handed_ever = bridge._codec_queue_peak = 0
    bridge._call_overlay_active = bridge._call_resume_pending = False
    bridge.boot_rom_enabled = True;bridge.line = None;bridge.audio_monitor = None
    bridge._audio_only = bridge.legacy_carrier_fallback = bridge._connected_event_queued = False
    return bridge


@pytest.fixture
def pair(monkeypatch):
    monkeypatch.setenv('COURIER_SIP_TX_BUFFER_MS', '0')
    monkeypatch.delenv('COURIER_SIP_RECORD', raising=False)
    cores = [core(), core()]
    sessions = [NativeSipSession.adopt(SipSession(SipConfig(server='127.0.0.1:9', bind='127.0.0.1')))
                for _ in range(2)]
    lines = [SipLine(session, exchange=LineExchange(first_digit_ms=1000000)) for session in sessions]
    for line in lines:line.cooperative_pacing = True
    lines[1] = NativeSipLine.adopt(lines[1])
    daas = [CourierDaa(), NativeDaa.adopt(CourierDaa())]
    for daa in daas:daa.seize()
    bridge = reference(cores[0], lines[0], daas[0])
    native = NativeBoardMedia(lines[1], daas[1], 64)
    try:
        yield bridge, native, cores
    finally:
        native.close()
        for line in lines:line.close()
        for device in cores:device.close()


def compare(bridge, native, cores):
    state = native.state
    assert state.reported_tx_index == bridge._line_service['tx_index']
    assert native.values(0) == bridge._exchange_line_buffer
    assert native.values(1) == list(bridge._codec_in_flight)
    assert native.values(2) == bridge._exchange_rx_samples
    assert (state.tx_index, state.tx_consumed, state.peak_codec, state.peak_line) == (
        bridge._exchange_tx_index, bridge._line_service['tx_consumed'],
        bridge._line_service['tx_peak_codec'], bridge._line_service['tx_peak_line'])
    assert (state.line_rx_peak, state.codec_in_peak, state.handed_peak, state.handed_at,
            state.handed_ever, state.queue_peak) == (
        bridge._line_rx_peak, bridge._codec_in_peak, bridge._codec_handed_peak,
        bridge._codec_handed_at, bridge._codec_handed_ever, bridge._codec_queue_peak)
    assert native.daa.status() == bridge.daa.status()
    for key in ('codec_rx_queued', 'codec_rx_consumed', 'codec_rx_peak'):
        assert cores[0].serial_state()[key] == cores[1].serial_state()[key], key
    assert cores[0].register(0x20) == cores[1].register(0x20)


def service(bridge, native, cores):
    bridge._instructions += 64
    bridge._service_exchange()
    native.service(cores[1], bridge._instructions)
    compare(bridge, native, cores)


def test_direct_pipeline_matches_reference_across_codec_clock_edges(pair):
    bridge, native, cores = pair
    for count, mclk, value in [(360, 2880000, 0x1200), (400, 2880000, 0x2400),
                              (480, 3840000, 0x1800), (540, 4032000, 0x2800),
                              (400, 2880000, 0x1000), (800, 3200000, 0x1400)]:
        for device in cores:advance(device, count, mclk, value)
        service(bridge, native, cores)
    assert native.state.frames >= 3


def test_undrained_transmit_batch_crosses_a_retune(pair):
    bridge, native, cores = pair
    for device in cores:
        advance(device, 380, 2880000, 0x1000)
        advance(device, 520, 3840000, 0x2800)
    service(bridge, native, cores)
    assert native.state.crossing_retune == bridge._line_service['tx_batches_crossing_retune'] == 1


def test_idle_codec_fallback_frame_uses_same_sample_clock(pair):
    from courier_emu.line import LINE_FRAME_INSTRUCTIONS
    bridge, native, cores = pair
    for _ in range((LINE_FRAME_INSTRUCTIONS+63)//64):service(bridge, native, cores)
    assert native.state.frames == 1


def test_clocked_adc_delivery_matches_reference(pair):
    bridge, native, cores = pair
    bridge.line = object()
    native.state.clocked_input = 1
    for count, mclk in [(760, 2880000), (960, 3840000), (720, 2880000)]:
        for device in cores:advance(device, count, mclk, 0x1200)
        service(bridge, native, cores)


def test_inactive_datapump_preserves_deferred_receive_audio(pair):
    bridge, native, cores = pair
    bridge.boot_rom_enabled = False
    native.state.queue_input = 0
    for device in cores:advance(device, 760, 2880000, 0x1200)
    service(bridge, native, cores)
    assert native.values(2)
    assert not native.values(1)


def test_reset_discards_old_tx_and_retains_stream_history(pair):
    bridge, native, cores = pair
    for device in cores:advance(device, 760, 2880000, 0x1200)
    service(bridge, native, cores)
    for device in cores:
        device.reset()
        configure(device)
    bridge._exchange_tx_index = 0
    bridge._exchange_line_buffer.clear()
    bridge._rx_cushion_rate = None
    native.reset(cores[1])
    service(bridge, native, cores)
    for device in cores:advance(device, 760, 3840000, 0x2400)
    service(bridge, native, cores)


def test_rebuild_replays_in_flight_adc_and_preserves_line_buffer(pair):
    bridge, native, cores = pair
    for device in cores:advance(device, 760, 2880000, 0x1200)
    service(bridge, native, cores)
    pending = len(bridge._codec_in_flight)
    assert pending
    for device in cores:device.close()
    cores[:] = [core(), core()]
    bridge.core = cores[0]
    bridge._exchange_tx_index = 0
    bridge._rx_cushion_rate = None
    bridge._codec_handed_peak = bridge._codec_handed_at = 0
    bridge.core.queue_codec_rx(list(bridge._codec_in_flight))
    native.reset(cores[1], rebuild=True)
    assert native.state.replayed == pending
    compare(bridge, native, cores)
    for device in cores:advance(device, 760, 3840000, 0x2400)
    service(bridge, native, cores)


def test_signalling_yield_resumes_frame_without_replaying_codec_audio(pair, monkeypatch):
    import socket
    bridge, native, cores = pair
    session = native.line.sip
    polls = []

    def consume_marker():
        session.socket.recvfrom(256)
        polls.append(1)

    monkeypatch.setattr(session, 'poll', consume_marker)
    for device in cores:advance(device, 760, 2880000, 0x1200)
    bridge._instructions += 64
    bridge._service_exchange()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
        peer.sendto(b'ready', session.socket.getsockname())
        assert native._lib.courier_board_media_begin(native.handle, cores[1].handle, bridge._instructions) == 0
        assert native._lib.courier_board_media_resume(native.handle, cores[1].handle) == 1
        with pytest.raises(RuntimeError, match='reset'):
            native.reset(cores[1])
        native.line.control_event(1)
        assert native._lib.courier_board_media_resume(native.handle, cores[1].handle) == 0
    assert polls == [1]
    assert native.state.frames == 1
    compare(bridge, native, cores)
