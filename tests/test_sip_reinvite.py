"""Media target refreshes must leave the connected modem alone."""
import pytest

from courier_emu.sip import SipConfig, SipSession


@pytest.fixture(params=['inbound', 'outbound'])
def connected(request):
    session = SipSession(SipConfig(server='127.0.0.1:9', bind='127.0.0.1'))
    session.state = 'connected'
    session.direction = request.param
    session.call_id = 'existing-call'
    session.from_tag = 'local'
    session.to_header = '<sip:peer@127.0.0.1>;tag=remote'
    session._incoming_headers = {'from': session.to_header}
    session.remote_rtp = ('127.0.0.1', 19000)
    session._rx_audio.extend([1, 2, 3])
    packets = []
    session._send_response = lambda packet, *args: packets.append(packet)
    try:
        yield session, packets
    finally:
        session.state = 'idle'
        session.close()


def invite(session, port=20000, cseq=8, codec='0', tag='local'):
    body = f'v=0\r\nc=IN IP4 127.0.0.1\r\nm=audio {port} RTP/AVP {codec}\r\n'.encode()
    return (f'INVITE sip:emu@127.0.0.1 SIP/2.0\r\n'
            f'From: <sip:peer@127.0.0.1>;tag=remote\r\n'
            f'To: <sip:emu@127.0.0.1>;tag={tag}\r\n'
            f'Call-ID: {session.call_id}\r\nCSeq: {cseq} INVITE\r\n'
            f'Via: SIP/2.0/UDP 127.0.0.1;branch=z9hG4bK{cseq}\r\n'
            f'Content-Length: {len(body)}\r\n\r\n').encode() + body


def test_target_refresh_replay_ack_and_return_to_bridge(connected):
    session, packets = connected
    packet = invite(session)
    session._handle_request(packet, session._dialog_peer)
    assert packets[-1].startswith(b'SIP/2.0 200 ')
    assert session.remote_rtp == ('127.0.0.1', 20000)
    assert session.state == 'connected'
    assert list(session._rx_audio) == [1, 2, 3]
    response = packets[-1]
    session._handle_request(packet, session._dialog_peer)
    assert packets[-1] == response
    ack = packet.split(b'\r\n\r\n')[0].replace(b'INVITE', b'ACK') + b'\r\n\r\n'
    session._handle_request(ack, session._dialog_peer)
    assert session._media_update['acked']
    session._handle_request(invite(session, port=19000, cseq=9), session._dialog_peer)
    assert session.remote_rtp == ('127.0.0.1', 19000)
    assert ('127.0.0.1', 19000) not in session._retired_rtp_peers


def test_rejected_offer_and_wrong_dialog_preserve_media(connected):
    session, packets = connected
    session._handle_request(invite(session, codec='8'), session._dialog_peer)
    assert packets[-1].startswith(b'SIP/2.0 488 ')
    assert session.remote_rtp == ('127.0.0.1', 19000)
    session._handle_request(invite(session, tag='wrong'), session._dialog_peer)
    assert packets[-1].startswith(b'SIP/2.0 481 ')
    assert session.state == 'connected'


def test_separate_call_is_busy_and_stale_update_is_rejected(connected):
    session, packets = connected
    packet = invite(session).replace(b'existing-call', b'other-call')
    packet = packet.replace(b';tag=local', b'')
    session._handle_request(packet, session._dialog_peer)
    assert packets[-1].startswith(b'SIP/2.0 486 ')
    session._remote_cseq = 9
    session._handle_request(invite(session), session._dialog_peer)
    assert packets[-1].startswith(b'SIP/2.0 500 ')
    assert session.remote_rtp == ('127.0.0.1', 19000)
