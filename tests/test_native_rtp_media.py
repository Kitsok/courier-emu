"""Local RTP packet/queue checks, without SIP or modem calls or benchmarks."""
import ctypes as c
import socket
import struct

import pytest

from courier_emu.analog_native import pcm
from courier_emu.media_native import NativeMedia, NativePeerSet, library
from courier_emu.sip import linear_to_ulaw, ulaw_to_linear, linear_to_alaw, alaw_to_linear


@pytest.mark.parametrize('law,encode,decode', [(0, linear_to_ulaw, ulaw_to_linear),
                                               (1, linear_to_alaw, alaw_to_linear)])
def test_native_g711_complete_domains(law, encode, decode):
    lib = library()
    samples = list(range(-32768, 32768))
    result = (c.c_int32 * len(samples))()
    lib.courier_rtp_convert(law, 1, pcm(samples), result, len(samples))
    assert list(result) == list(map(encode, samples))
    octets = list(range(256))
    decoded = (c.c_int32 * len(octets))()
    lib.courier_rtp_convert(law, 0, pcm(octets), decoded, len(octets))
    assert list(decoded) == list(map(decode, octets))


@pytest.fixture
def transport():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as local, \
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
        local.bind(('127.0.0.1', 0));peer.bind(('127.0.0.1', 0));peer.settimeout(1)
        media = NativeMedia(local.fileno(), sequence=65535, timestamp=0xffffff60, ssrc=0x12345678)
        media.configure(5, 0, 0, False, 1.0)
        media.remote(peer.getsockname())
        media.set('next_at', 10.0)
        try:
            yield media, local, peer
        finally:
            media.close()


@pytest.mark.parametrize('law,encode', [(0, linear_to_ulaw), (1, linear_to_alaw)])
def test_native_rtp_headers_gain_and_clock_wrap(transport, law, encode):
    media, local, peer = transport
    media.configure(5, 8 if law else 0, law, False, .25)
    samples = [-32768, -6, -2, 0, 2, 6, 32767, 1000] * 20
    media.send(samples, now=10.0)
    packet = peer.recvfrom(2048)[0]
    assert packet[:12] == struct.pack('!BBHII', 0x80, 8 if law else 0, 65535, 0xffffff60, 0x12345678)
    assert packet[12:] == bytes(encode(round(sample*.25)) for sample in samples)
    state = media.snapshot()
    assert (state.sequence, state.timestamp, state.packets_sent, state.octets_sent) == (0, 0, 1, 160)
    assert state.next_at == 10.02


@pytest.mark.parametrize('law,decode', [(0, ulaw_to_linear), (1, alaw_to_linear)])
def test_native_receive_domains_retired_peers_and_payload_filter(transport, law, decode):
    media, local, peer = transport
    payload = 8 if law else 0
    media.configure(5, payload, law, False, 1)
    packet = bytes((0x80, payload)) + bytes(10) + bytes(range(256))
    retired = NativePeerSet(media)
    retired.add(peer.getsockname())
    peer.sendto(packet, local.getsockname());media.poll(10)
    assert not media.queues[1]
    retired.discard(peer.getsockname())
    peer.sendto(packet, local.getsockname())
    peer.sendto(bytes((0x80, 97)) + packet[2:], local.getsockname())
    media.poll(10)
    assert list(media.queues[1]) == [decode(value) for value in range(256)]
    assert media.snapshot().packets_received == 1
    assert media.snapshot().octets_received == 256
    assert media.values(1, 100, True) == [decode(value) for value in range(100)]
    assert len(media.queues[1]) == 156


def test_native_codeword_transport_never_applies_law_or_gain(transport):
    media, local, peer = transport
    media.configure(5, 97, 1, True, .25)
    values = bytes(range(160))
    media.send(values, codewords=True, now=10)
    assert peer.recvfrom(2048)[0][12:] == values
    peer.sendto(bytes((0x80, 97)) + bytes(10) + values, local.getsockname())
    media.poll(10)
    assert bytes(media.queues[3]) == values
    assert not media.queues[1]


def test_native_preanswer_discard_and_audio_queue_limit(transport):
    media, local, peer = transport
    media.configure(3, 0, 0, False, 1)
    media.send([1000] * 320, now=10)
    assert media.snapshot().preanswer_discarded == 320
    assert not media.queues[0]
    media.queues[0].extend(range(20000))
    assert len(media.queues[0]) == 16000
    assert media.queues[0].popleft() == 4000
    media.queues[0].clear()
    media.configure(5, 0, 0, False, 1)
    media.send([2000] * 160, now=10)
    assert peer.recvfrom(2048)[0][12:] == bytes([linear_to_ulaw(2000)]) * 160


def test_native_clock_reserve_and_underflow_preserve_every_sample(transport):
    media, local, peer = transport
    media.enable_clock(320)
    media.send([1000] * 160)
    peer.settimeout(.05)
    with pytest.raises(TimeoutError):peer.recvfrom(2048)
    media.send([2000] * 160)
    peer.settimeout(1)
    first, second = peer.recvfrom(2048)[0], peer.recvfrom(2048)[0]
    assert first[12:] == bytes([linear_to_ulaw(1000)]) * 160
    assert second[12:] == bytes([linear_to_ulaw(2000)]) * 160
    assert struct.unpack('!I', second[4:8])[0] == 0
    # An exhausted producer must rebuild the reserve, rather than transmit
    # fabricated silence or throw away the first packet of resumed data.
    peer.settimeout(.05)
    with pytest.raises(TimeoutError):peer.recvfrom(2048)
    media.send([3000] * 160)
    with pytest.raises(TimeoutError):peer.recvfrom(2048)
    media.send([4000] * 160)
    peer.settimeout(1)
    assert peer.recvfrom(2048)[0][12:] == bytes([linear_to_ulaw(3000)]) * 160
    assert peer.recvfrom(2048)[0][12:] == bytes([linear_to_ulaw(4000)]) * 160


def test_native_transport_owns_a_duplicate_and_keeps_final_counters():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
        local = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        local.bind(('127.0.0.1', 0));address = local.getsockname()
        media = NativeMedia(local.fileno())
        local.close()
        try:
            peer.sendto(bytes((0x80, 0)) + bytes(10) + b'\xff'*160, address)
            media.poll(1)
            assert media.snapshot().packets_received == 1
        finally:
            media.close()
        assert media.snapshot().packets_received == 1
        media.close()


def test_native_sip_media_adoption_keeps_identity_and_control_plane_views():
    from courier_emu.media_native import NativeSipSession
    from courier_emu.sip import SipConfig, SipSession
    session = SipSession(SipConfig(server='127.0.0.1:9', bind='127.0.0.1'))
    session._rtp_sequence = 7
    session._rtp_timestamp = 160
    session._rx_audio.extend([12, 34])
    try:
        assert NativeSipSession.adopt(session) is session
        assert session._rtp_sequence == 7 and session._rtp_timestamp == 160
        assert session.receive_audio() == [12, 34]
        assert not session._rx_audio
        session._retired_rtp_peers.add(('127.0.0.1', 12345))
        assert set(session._retired_rtp_peers) == {('127.0.0.1', 12345)}
        session._retired_rtp_peers = set()
        assert not session._retired_rtp_peers
        session.enable_media_clock(buffer_samples=320)
        assert session._rtp_clock_thread is None  # No Python media thread.
        assert session.status()['rtp_tx_buffer_samples'] == 320
    finally:
        session.close()
    assert session.status()['rtp_packets_sent'] == 0


@pytest.mark.parametrize('native', [False, True])
def test_sip_receive_adapter_preserves_packet_counters_and_audio(native):
    from courier_emu.media_native import NativeSipSession
    from courier_emu.sip import SipConfig, SipSession
    session = SipSession(SipConfig(server='127.0.0.1:9', bind='127.0.0.1'))
    try:
        if native:NativeSipSession.adopt(session)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
            values = bytes(range(256))
            peer.sendto(b'\x80\x00'+bytes(10)+values, session.rtp_socket.getsockname())
            session.poll()  # No SIP dialog or modem call is created.
        assert session.receive_audio() == list(map(ulaw_to_linear, values))
        assert not session.receive_audio()
        assert session.status()['rtp_packets_received'] == 1
        assert session.status()['rtp_octets_received'] == 256
    finally:
        session.close()
