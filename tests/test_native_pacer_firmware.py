"""Positive-lead pacing must preserve fixed-work firmware and device state."""
import socket
import time
from courier_emu.codec import CodecBringUp, SiliconDaa
from courier_emu.console import SerialConsole
from courier_emu.daa import CourierDaa
from courier_emu.exchange import LineExchange
from courier_emu.images import load_image
from courier_emu.machine import CourierMachine
from courier_emu.nvram import CourierNvram
from courier_emu.profiles import ROOT, ANALOG403_IMAGE
from courier_emu.sip import SipConfig, SipSession


def test_positive_lead_preserves_firmware_state(monkeypatch):
    states = []
    for enabled in ('0', '1'):
        monkeypatch.setenv('COURIER_NATIVE_PACER_WAIT', enabled)
        terminal, transport = socket.socketpair()
        console = SerialConsole(transport.detach())
        sip = SipSession(SipConfig(server='127.0.0.1:9', bind='127.0.0.1'))
        try:
            machine = CourierMachine(load_image(ROOT/ANALOG403_IMAGE), with_dsp=True,
                nvram=CourierNvram.idsl403_lapm_fixture(), board_id=7,
                daa=CourierDaa('quiet'), exchange=LineExchange(),
                codec=CodecBringUp(SiliconDaa(1)), dsp_batch=4096,
                tick_source='dsp', sip=sip, console=console)
            machine.dsp_bridge._sip_line._next_frame_at = time.monotonic()+60
            result = machine.run(8_000_000).to_dict()
            assert result['error'] is None
            states.append(dict(memory=bytes(machine.uc.memory), registers=list(machine.uc.regs),
                dsp=result['dsp_bridge']['dsp'], serial=result['dsp_bridge']['serial_port'],
                timers=machine.timers.status(), io=machine.io_counts,
                service=bytes(machine._native_service_state),
                queue=machine.dsp_queue_write_counts))
            waits = machine._worker_poll.state.pacer_wait.waits
            assert (waits > 0) == (enabled == '1')
        finally:
            console.close(); terminal.close(); sip.close()
    assert states[0] == states[1]
