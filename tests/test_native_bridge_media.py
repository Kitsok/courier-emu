"""Native bridge construction and live media views; no modem calls."""
from pathlib import Path
import struct

import pytest

from courier_emu.bridge import CourierDspBridge
from courier_emu.bridge_native import NativeCourierDspBridge
from courier_emu.daa import CourierDaa
from courier_emu.dsp import NativeC5x
from courier_emu.exchange import LineExchange
from courier_emu.images import load_image
from courier_emu.media_native import NativeSipSession
from courier_emu.profiles import ANALOG403_IMAGE, ROOT
from courier_emu.sip import SipConfig, SipSession


def controlled_core():
    core = NativeC5x.from_program(0, struct.pack('<H', 0xbe22))
    core.configure_rom_codec();core.configure_line_frame_interrupt(5, 0xffff)
    for word in (3, 0x010a, 3, 0x0214):core.host_write(0x21, word)
    return core


@pytest.fixture
def bridge(monkeypatch):
    path = ROOT / ANALOG403_IMAGE
    if not path.exists():pytest.skip('optional analog403 image unavailable')
    monkeypatch.setenv('COURIER_NATIVE_BOARD', '1')
    monkeypatch.setenv('COURIER_SIP_TX_BUFFER_MS', '150')
    monkeypatch.delenv('COURIER_SIP_RECORD', raising=False)
    session = SipSession(SipConfig(server='127.0.0.1:9', bind='127.0.0.1'))
    daa, exchange = CourierDaa(), LineExchange(first_digit_ms=1000000)
    device = CourierDspBridge(load_image(path), daa=daa, sip=session, exchange=exchange)
    device._sip_line.cooperative_pacing = True
    try:
        yield device, session, daa, exchange
    finally:
        device.close()


def test_constructor_adopts_devices_before_starting_media_clock(bridge):
    device, session, daa, exchange = bridge
    assert isinstance(device, NativeCourierDspBridge)
    assert isinstance(session, NativeSipSession)
    assert device.sip is session and device.daa is daa and device.exchange is exchange
    assert session._rtp_clock_thread is None
    assert session.status()['rtp_tx_buffer_samples'] == 1200
    assert device._codec_to_line._timed is None
    device._codec_handed_at = 91
    assert device._native_media_owner.state.handed_at == 91
    device._native_media_owner.state.handed_at = 92
    assert device._codec_handed_at == 92
    device._line_service['tx_consumed'] = 19
    assert device._native_media_owner.state.tx_consumed == 19
    device._native_media_owner.state.tx_consumed = 20
    assert dict(device._line_service)['tx_consumed'] == 20


def test_native_queue_views_support_control_operations_and_close(bridge):
    device, *_ = bridge
    queue = device._exchange_line_buffer
    queue.extend([1, 2, 3]);queue.append(4)
    assert list(queue) == [1, 2, 3, 4]
    queue[1:3] = [7, 8]
    del queue[:1]
    assert queue.popleft() == 7
    assert queue[:] == [8, 4]
    queue.clear()
    assert not queue
    device._codec_in_flight.extend([100, 200])
    assert list(device._codec_in_flight) == [100, 200]
    device._native_media_owner.close()
    assert list(device._codec_in_flight) == [100, 200]
    assert device._codec_to_line.converted == 0
    assert device.dial_digits == ''


def test_core_replacement_replays_fifo_once_and_updates_live_state(bridge):
    device, *_ = bridge
    old_core = device.core
    device._codec_in_flight.extend([0x1200, -800]*40)
    device._exchange_line_buffer.extend([1, 2, 3])
    device._codec_handed_peak = 800
    replacement = controlled_core()
    device.core = replacement
    old_core.close()
    assert replacement.serial_state()['codec_rx_queued'] == 80
    assert device._codec_replayed == 80
    assert device._codec_handed_peak == 0
    assert list(device._exchange_line_buffer) == [1, 2, 3]
    assert device._exchange_tx_index == 0


def test_explicit_receive_and_transmit_use_native_streams(bridge):
    device, _, daa, _ = bridge
    old_core = device.core
    device.core = controlled_core();old_core.close()
    daa.seize()
    device._instructions = 123
    device._queue_line_audio([800]*800)
    assert device._codec_handed_at == 123
    assert device._codec_in_peak == 800
    assert device._line_rx_peak == device._codec_queue_peak == 0
    assert len(device._codec_in_flight) > 0
    assert device._rx_cushion_rate == 7200
    device.core.host_write(0x21, 0x1200)
    for _ in range(80):
        state = device.core.codec_state()
        device.core.step_cycles(state['line_frame_next_cycle']-state['cycles'])
    device._take_line_audio()
    assert device._exchange_tx_index == 80
    assert device._line_service['tx_peak_codec'] == 0x1200
    assert device._codec_to_line.converted == len(device._exchange_line_buffer)


def test_frame_service_updates_native_dial_digits_and_daa(bridge):
    device, _, daa, exchange = bridge
    daa.seize()
    exchange.dialed = '123'
    # Do not execute a modem command or SIP route: use a held connected loop
    # state with an idle SIP peer and no router while exercising frame ownership.
    exchange.state = 'connected';exchange.off_hook = True
    device.dial_digits = 'commanded'
    assert device.dial_digits == 'commanded'
    device._exchange_line_buffer.extend([0]*800)
    device.core.host_write(0x21, 0x1200)
    state = device.core.codec_state()
    device.core.step_cycles(state['frame_period'])
    device._service_exchange()
    assert device.dial_digits == '123'
    assert daa.operation == 'dialing'
    assert device._native_media_owner.state.frames >= 1


def test_shared_reset_edge_clears_native_output_cursors_and_buffer(bridge):
    device, *_ = bridge
    device.set_reset(False)
    device._exchange_tx_index = 91
    device._line_service['tx_index'] = 91
    device._exchange_line_buffer.extend([1, 2, 3])
    device._codec_in_flight.extend([400, 500])
    device._rx_cushion_rate = 7200
    device.set_reset(True)
    assert device._exchange_tx_index == 0
    assert device._line_service['tx_index'] == 91
    assert not device._exchange_line_buffer
    assert list(device._codec_in_flight) == [400, 500]
    assert device._rx_cushion_rate is None


def test_optional_monitor_runs_before_adc_queue_and_once_per_frame(bridge):
    device, *_ = bridge
    delivered = []

    class Monitor:
        def feed(self, tx, rx, *, enabled):
            delivered.append((list(tx), list(rx), enabled,
                              device._native_media_owner.state.frames, len(device._codec_in_flight)))
        def close(self):pass

    device.audio_monitor = Monitor()
    device.speaker_enabled = lambda: True
    device._exchange_line_buffer.extend(range(800))
    device.core.host_write(0x21, 0x1200)
    state = device.core.codec_state()
    device.core.step_cycles(state['frame_period'])
    device._service_exchange()
    assert len(delivered) == 1
    tx, rx, enabled, frames, queued = delivered[0]
    assert tx == list(range(800)) and rx == [0]*800
    assert enabled and frames == 0 and queued == 0
    assert device._native_media_owner.state.frames == 1
    assert len(device._codec_in_flight) >= 800
    device.audio_monitor = None


def test_native_default_and_explicit_reference_switch(bridge, monkeypatch):
    existing, *_ = bridge
    for setting, expected in [(None, True), ('0', False)]:
        if setting is None:monkeypatch.delenv('COURIER_NATIVE_BOARD', raising=False)
        else:monkeypatch.setenv('COURIER_NATIVE_BOARD', setting)
        session = SipSession(SipConfig(server='127.0.0.1:9', bind='127.0.0.1'))
        device = CourierDspBridge(existing.image, daa=CourierDaa(), sip=session, exchange=LineExchange())
        try:
            assert isinstance(device, NativeCourierDspBridge) == expected
            assert isinstance(session, NativeSipSession) == expected
            assert (session._rtp_clock_thread is None) == expected
        finally:
            device.close()
