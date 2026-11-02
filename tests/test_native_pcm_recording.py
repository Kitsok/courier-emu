"""Local PCM recording scripts; no SIP dialogs or modem calls."""
import wave
import struct

from courier_emu.ata import SipLine
from courier_emu.media_native import NativeSipSession
from courier_emu.sip import SipConfig, SipSession
from courier_emu.sip_line_native import NativeSipLine


def test_native_recordings_preserve_pcm_and_silence_padding(tmp_path, monkeypatch):
    prefix = tmp_path/'native'
    monkeypatch.setenv('COURIER_SIP_RECORD', str(prefix))
    monkeypatch.setenv('COURIER_SIP_TX_BUFFER_MS', '0')
    session = NativeSipSession.adopt(SipSession(SipConfig(server='127.0.0.1:9', bind='127.0.0.1')))
    monkeypatch.setattr(session, 'poll', lambda: None)
    line = NativeSipLine.adopt(SipLine(session))
    line.cooperative_pacing = True
    try:
        session.state = 'connected'
        line.exchange.state = 'connected';line.exchange.off_hook = True
        session._native_media.queues[1].extend([23, -42]*50)
        received = line.service(True, [40000, -40000, 123], 160)
        assert received == [23, -42]*50+[0]*60
    finally:
        session.state = 'idle';line.close()
    for side, expected in [('tx', [32767, -32768, 123]+[0]*157),
                           ('rx', [23, -42]*50+[0]*60)]:
        with wave.open(str(prefix)+f'-{side}.wav', 'rb') as recording:
            assert (recording.getnchannels(), recording.getsampwidth(), recording.getframerate()) == (1, 2, 8000)
            assert recording.getnframes() == 160
            assert recording.readframes(160) == struct.pack('<160h', *expected)
