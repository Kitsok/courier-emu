"""Receive complete G.711 codeword domains through the UDP packet path."""
import socket

import pytest

from courier_emu.sip import SipConfig, SipSession, alaw_to_linear, ulaw_to_linear


@pytest.mark.parametrize('codec,decode', [('pcmu', ulaw_to_linear), ('pcma', alaw_to_linear)])
def test_rtp_decodes_every_codeword_in_order(codec, decode):
    session = SipSession(SipConfig(server='127.0.0.1:9', bind='127.0.0.1', codec=codec))
    try:
        payload = bytes(range(256)) + bytes(reversed(range(256)))
        packet = bytes((0x80, session.payload_type)) + bytes(10) + payload
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
            peer.sendto(packet, session.rtp_socket.getsockname())
        session.poll()
        assert list(session._rx_audio) == [decode(value) for value in payload]
        assert session.rtp_packets_received == 1
        assert session.rtp_octets_received == len(payload)
    finally:
        session.close()


def test_rtp_codeword_mode_preserves_octets():
    session = SipSession(SipConfig(server='127.0.0.1:9', bind='127.0.0.1', codec='clearmode'))
    try:
        session.codewords = True
        payload = bytes(range(256))
        packet = bytes((0x80, session.payload_type)) + bytes(10) + payload
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
            peer.sendto(packet, session.rtp_socket.getsockname())
        session.poll()
        assert bytes(session._rx_codewords) == payload
        assert not session._rx_audio
    finally:
        session.close()
