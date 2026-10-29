"""Incoming analog supervision from a peer other than the configured server."""
import socket
import time

import pytest

from courier_emu.ata import SipLine
from courier_emu.sip import SipConfig, SipSession


@pytest.fixture
def incoming(monkeypatch):
    monkeypatch.setenv("COURIER_SIP_TX_BUFFER_MS", "0")
    peer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    peer.bind(("127.0.0.1", 0))
    peer.settimeout(1)
    session = SipSession(SipConfig(server="127.0.0.1:9", bind="127.0.0.1"))
    line = SipLine(session)
    line._pace = lambda _: None
    try:
        yield session, line, peer
    finally:
        session.close()
        peer.close()


def request(method="INVITE", call_id="caller", to="<sip:courier@127.0.0.1>", branch="incoming"):
    body = (b"v=0\r\nc=IN IP4 127.0.0.1\r\nm=audio 19000 RTP/AVP 0\r\n"
            b"a=rtpmap:0 PCMU/8000\r\n") if method == "INVITE" else b""
    return (f"{method} sip:courier@127.0.0.1 SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP 127.0.0.1;branch=z9hG4bK{branch}\r\n"
            f"From: <sip:physical@127.0.0.1>;tag=remote\r\nTo: {to}\r\n"
            f"Call-ID: {call_id}\r\nCSeq: 7 {method}\r\n"
            "Contact: <sip:physical@127.0.0.1>\r\n"
            f"Content-Length: {len(body)}\r\n\r\n").encode() + body


def send(peer, session, packet):
    peer.sendto(packet, ("127.0.0.1", session.local_port))


def offer(session, line, peer):
    send(peer, session, request())
    line.service(False, [], 80)
    assert peer.recvfrom(8192)[0].startswith(b"SIP/2.0 100 ")
    assert peer.recvfrom(8192)[0].startswith(b"SIP/2.0 180 ")


def test_analog_ring_answer_ack_and_remote_hangup(incoming):
    session, line, peer = incoming
    offer(session, line, peer)
    assert line.exchange.state == "ringing"
    assert session.state == "ringing" and session.direction == "inbound"
    line.service(True, [], 80)
    response = peer.recvfrom(8192)[0]
    assert response.startswith(b"SIP/2.0 200 ")
    assert line.exchange.state == "connected"
    values = dict(item.split(": ", 1) for item in response.decode().split("\r\n")[1:] if ": " in item)
    send(peer, session, request("ACK", to=values["To"]))
    line.service(True, [], 80)
    assert session._incoming_acked
    send(peer, session, request("BYE", to=values["To"]))
    line.service(True, [], 80)
    assert peer.recvfrom(8192)[0].startswith(b"SIP/2.0 200 ")
    assert line.exchange.state == "released" and session.state == "closed"


def test_cancel_stops_ringing_and_duplicate_invite_stays_cancelled(incoming):
    session, line, peer = incoming
    offer(session, line, peer)
    send(peer, session, request("CANCEL", call_id="unrelated"))
    line.service(False, [], 80)
    assert peer.recvfrom(8192)[0].startswith(b"SIP/2.0 481 ")
    assert line.exchange.state == "ringing"
    send(peer, session, request("CANCEL"))
    line.service(False, [], 80)
    assert peer.recvfrom(8192)[0].startswith(b"SIP/2.0 200 ")
    assert peer.recvfrom(8192)[0].startswith(b"SIP/2.0 487 ")
    assert line.exchange.state == "idle"
    send(peer, session, request())
    line.service(False, [], 80)
    assert peer.recvfrom(8192)[0].startswith(b"SIP/2.0 487 ")
    assert line.exchange.state == "idle"


def test_busy_response_goes_to_second_peer_without_stealing_dialog(incoming):
    session, line, peer = incoming
    offer(session, line, peer)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as other:
        other.bind(("127.0.0.1", 0))
        other.settimeout(1)
        send(other, session, request(call_id="other"))
        line.service(False, [], 80)
        assert other.recvfrom(8192)[0].startswith(b"SIP/2.0 486 ")
        assert session.call_id == "caller"
        assert session._incoming_peer == peer.getsockname()


def test_unanswered_call_is_rejected_after_ring_budget(incoming):
    session, line, peer = incoming
    offer(session, line, peer)
    line.exchange.incoming_rings = 1
    line.service(False, [], 6 * line.line_rate)
    assert peer.recvfrom(8192)[0].startswith(b"SIP/2.0 480 ")
    assert line.exchange.state == "idle"


def test_answer_is_retransmitted_until_valid_ack(incoming, monkeypatch):
    session, line, peer = incoming
    offer(session, line, peer)
    line.service(True, [], 80)
    answer = peer.recvfrom(8192)[0]
    monkeypatch.setattr("courier_emu.sip.time.monotonic", lambda: session._incoming_final_at + 1)
    session.poll()
    assert peer.recvfrom(8192)[0] == answer
    send(peer, session, request("ACK", call_id="unrelated"))
    session.poll()
    assert not session._incoming_acked
    send(peer, session, request("ACK"))
    session.poll()
    assert session._incoming_acked


def test_shutdown_rejects_ringing_instead_of_sending_cancel(incoming):
    session, line, peer = incoming
    offer(session, line, peer)
    session.close()
    assert peer.recvfrom(8192)[0].startswith(b"SIP/2.0 480 ")
