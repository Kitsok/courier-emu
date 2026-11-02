"""Boot-only native worker regression: no AT commands, SIP dialogs or calls."""
import pytest

from courier_emu.codec import CodecBringUp, SiliconDaa
from courier_emu.daa import CourierDaa
from courier_emu.exchange import LineExchange
from courier_emu.images import load_image
from courier_emu.machine import CourierMachine
from courier_emu.nvram import CourierNvram
from courier_emu.profiles import ROOT, ANALOG403_IMAGE
from courier_emu.sip import SipConfig, SipSession


class Console:
    poll_instructions = 8192
    closed = False

    def __init__(self):
        self.output = [];self.owner = None;self.injected = False

    def poll(self, limit):
        if self.owner.instructions >= 4_000_000 and not self.injected:
            # A device-state edge only: no hook seizure or call is initiated.
            self.owner.dsp_bridge.daa.line_state = 'disconnected'
            # Console polls coincide with exchange service boundaries. Shift
            # the device phase so the following native service sees the edge.
            self.owner.dsp_bridge._exchange_instructions = 0
            self.injected = True
        return b''
    def write(self, byte):self.output.append(byte)
    def show_lamps(self, line):pass
    def close(self):pass
    def summary(self):return {}


def test_boot_state_matches_python_worker_with_native_media(monkeypatch):
    path = ROOT / ANALOG403_IMAGE
    if not path.exists():pytest.skip('optional captured analog403 image unavailable')
    monkeypatch.setenv('COURIER_NATIVE_BOARD', '1')
    monkeypatch.setenv('COURIER_SIP_TX_BUFFER_MS', '0')
    monkeypatch.delenv('COURIER_SIP_RECORD', raising=False)
    machines, results = [], []
    for enabled in ('0', '1'):
        monkeypatch.setenv('COURIER_WORKER_POLL', enabled)
        session = SipSession(SipConfig(server='127.0.0.1:9', bind='127.0.0.1'))
        machine = CourierMachine(
            load_image(path), with_dsp=True, nvram=CourierNvram.idsl403_lapm_fixture(),
            board_id=7, daa=CourierDaa('quiet'), exchange=LineExchange(),
            codec=CodecBringUp(SiliconDaa(1)), dsp_batch=4096, console=Console(),
            sip=session, tick_source='dsp')
        machine.console.owner = machine
        machine.dsp_bridge._sip_line.cooperative_pacing = True
        result = machine.run(8_000_000)
        assert result.error is None
        assert machine.dsp_bridge._sip_line.placed == 0
        assert session.rtp_packets_sent == 0
        machines.append(machine);results.append(result)
    assert bytes(machines[0]._native_service_state) == bytes(machines[1]._native_service_state)
    assert results[0].registers == results[1].registers
    assert machines[0].uc.memory == machines[1].uc.memory
    assert machines[0].io_counts == machines[1].io_counts
    assert results[0].serial_text == results[1].serial_text
    assert results[0].ticks == results[1].ticks
    assert results[0].timer_interrupts == results[1].timer_interrupts
    left, right = [machine.dsp_bridge for machine in machines]
    assert left._last_state == right._last_state
    assert bytes(left._native_media_owner.state) == bytes(right._native_media_owner.state)
    assert left.exchange.status() == right.exchange.status()
    assert left.daa.status() == right.daa.status()
    assert left.codec.status() == right.codec.status()
    assert list(left._codec_in_flight) == list(right._codec_in_flight)
    assert list(left._exchange_line_buffer) == list(right._exchange_line_buffer)
    assert results[1].scheduler['native_media_services'] > 0
    assert results[1].scheduler['native_dsp_batches'] > 0
    assert results[1].scheduler['native_media_yields'] > 0
    assert results[1].scheduler['native_codec_services'] > 0
