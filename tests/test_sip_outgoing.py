"""Exercise outgoing dialogs and cancellation against a real loopback peer."""
import socket
import time

import pytest

from courier_emu.ata import SipLine
from courier_emu.sip import SipConfig, SipSession


@pytest.fixture
def dialog():
    peer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    peer.bind(("127.0.0.1", 0))
    peer.settimeout(1)
    session = SipSession(SipConfig(server=f"127.0.0.1:{peer.getsockname()[1]}"))
    try:
        yield session, peer
    finally:
        session.close()
        peer.close()


def headers(packet):
    return dict(line.split(": ", 1) for line in packet.decode().split("\r\n")[1:] if ": " in line)


def respond(peer, address, invite, status, *, call_id=None, sequence=None):
    values = headers(invite)
    body = (b"v=0\r\nc=IN IP4 127.0.0.1\r\nm=audio 19000 RTP/AVP 0\r\n"
            b"a=rtpmap:0 PCMU/8000\r\n") if status == 200 else b""
    packet = (f"SIP/2.0 {status} Test\r\nVia: {values['Via']}\r\n"
              f"From: {values['From']}\r\nTo: {values['To']};tag=peer\r\n"
              f"Call-ID: {call_id or values['Call-ID']}\r\n"
              f"CSeq: {sequence or values['CSeq']}\r\n"
              "Contact: <sip:answer@127.0.0.1>\r\n"
              f"Content-Length: {len(body)}\r\n\r\n").encode() + body
    peer.sendto(packet, address)


def test_cancel_crossing_answer_never_resurrects_call(dialog):
    session, peer = dialog
    session.start_call("100")
    invite, address = peer.recvfrom(8192)
    assert invite.startswith(b"INVITE sip:100@127.0.0.1 ")
    respond(peer, address, invite, 180)
    session.poll()
    assert session.state == "ringing"
    session.hangup()
    cancel, _ = peer.recvfrom(8192)
    assert cancel.startswith(b"CANCEL ")
    assert headers(cancel)["Via"] == headers(invite)["Via"]
    assert headers(cancel)["CSeq"].split()[0] == headers(invite)["CSeq"].split()[0]
    respond(peer, address, invite, 200)
    session.poll()
    ack, _ = peer.recvfrom(8192)
    bye, _ = peer.recvfrom(8192)
    assert ack.startswith(b"ACK sip:answer@127.0.0.1 ")
    assert bye.startswith(b"BYE sip:answer@127.0.0.1 ")
    assert session.state == "idle" and session.remote_rtp is None


def test_stale_response_cannot_change_new_call(dialog):
    session, peer = dialog
    session.start_call("100")
    old, address = peer.recvfrom(8192)
    session.hangup()
    peer.recvfrom(8192)
    session.start_call("101")
    new, _ = peer.recvfrom(8192)
    respond(peer, address, old, 200)
    session.poll()
    assert session.state == "inviting" and session.number == "101"
    assert session.call_id == headers(new)["Call-ID"]
    assert headers(peer.recvfrom(8192)[0])["Call-ID"] == headers(old)["Call-ID"]
    assert headers(peer.recvfrom(8192)[0])["Call-ID"] == headers(old)["Call-ID"]


def test_busy_ack_uses_invite_branch_and_next_call_is_fresh(dialog):
    session, peer = dialog
    session.start_call("100")
    invite, address = peer.recvfrom(8192)
    respond(peer, address, invite, 486, call_id="unrelated")
    respond(peer, address, invite, 486, sequence="999 INVITE")
    session.poll()
    assert session.state == "inviting"
    respond(peer, address, invite, 486)
    session.poll()
    ack, _ = peer.recvfrom(8192)
    assert headers(ack)["Via"] == headers(invite)["Via"]
    assert session.state == "failed" and session.last_status == 486
    session.start_call("101")
    next_invite, _ = peer.recvfrom(8192)
    assert headers(next_invite)["Call-ID"] != headers(invite)["Call-ID"]
    assert session.last_status == 0 and session.remote_rtp is None


def test_setup_timeout_cancels_transaction(dialog):
    session, peer = dialog
    session.start_call("100")
    peer.recvfrom(8192)
    session._invite_deadline = time.monotonic() - 1
    session.poll()
    assert session.state == "failed" and session.last_status == 408
    assert peer.recvfrom(8192)[0].startswith(b"CANCEL ")


def test_answer_and_hangup_use_the_accepted_dialog(dialog):
    session, peer = dialog
    session.start_call("100")
    invite, address = peer.recvfrom(8192)
    respond(peer, address, invite, 200)
    session.poll()
    assert peer.recvfrom(8192)[0].startswith(b"ACK sip:answer@127.0.0.1 ")
    assert session.state == "connected"
    assert session.remote_rtp == ("127.0.0.1", 19000)
    session._next_rtp_at = 123.0
    respond(peer, address, invite, 200)
    session._handle_response(peer_packet(session), peer.getsockname())
    assert peer.recvfrom(8192)[0].startswith(b"ACK ")
    assert session._next_rtp_at == 123.0
    session.hangup()
    assert peer.recvfrom(8192)[0].startswith(b"BYE sip:answer@127.0.0.1 ")
    assert session.state == "idle" and session.remote_rtp is None


def peer_packet(session):
    # Wait for a loopback datagram without polling RTP or changing its clock.
    import select
    assert select.select([session.socket], [], [], 1)[0]
    return session.socket.recvfrom(8192)[0]


def test_unsupported_answer_is_acknowledged_and_torn_down(dialog):
    session, peer = dialog
    session.start_call("100")
    invite, address = peer.recvfrom(8192)
    respond(peer, address, invite, 200)
    packet = peer_packet(session).replace(b"RTP/AVP 0", b"RTP/AVP 8")
    session._handle_response(packet, peer.getsockname())
    assert session.state == "failed"
    assert peer.recvfrom(8192)[0].startswith(b"ACK ")
    assert peer.recvfrom(8192)[0].startswith(b"BYE ")


def test_analog_loop_cancels_and_receives_busy_without_fake_carrier(dialog, monkeypatch):
    session, peer = dialog
    monkeypatch.setenv("COURIER_SIP_TX_BUFFER_MS", "0")
    line = SipLine(session)
    line.exchange._enter("routing")
    assert line._route("100") is None
    invite, address = peer.recvfrom(8192)
    respond(peer, address, invite, 486)
    session.poll()
    line.exchange._enter("ringback")
    line._follow_sip()
    assert line.exchange.state == "busy"
    peer.recvfrom(8192)  # ACK
    session.start_call("101")
    peer.recvfrom(8192)
    line.exchange._enter("idle")
    line._follow_loop()
    assert session.state == "idle"
    assert peer.recvfrom(8192)[0].startswith(b"CANCEL ")
