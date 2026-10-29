"""Boot analog firmware against loopback SIP, without calling hardware."""
import os
from pathlib import Path
import select
import socket
import subprocess
import time
import pytest


ROOT = Path(__file__).resolve().parent.parent


def test_firmware_dials_and_keypress_cancels(tmp_path):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
        peer.bind(("127.0.0.1", 0))
        peer.setblocking(False)
        # Obtain private ports; the runtime deliberately disallows port zero.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sip_port, \
                socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rtp_port:
            sip_port.bind(("127.0.0.1", 0))
            rtp_port.bind(("127.0.0.1", 0))
            local_sip = sip_port.getsockname()[1]
            local_rtp = rtp_port.getsockname()[1]
        config = (ROOT / "courier-emu.ini").read_text()
        config = config.replace("server = 192.168.196.29:5060",
                                f"server = 127.0.0.1:{peer.getsockname()[1]}")
        config = config.replace("192.168.196.29", "127.0.0.1")
        config = config.replace("bind = 0.0.0.0", "bind = 127.0.0.1")
        config = config.replace("port = 5074", f"port = {local_sip}")
        config = config.replace("rtp_port = 4014", f"rtp_port = {local_rtp}")
        location = tmp_path / "modem.ini"
        location.write_text(config)
        terminal = tmp_path / "artifacts/courier-emu.tty"
        with (tmp_path / "worker.json").open("w") as report, \
                (tmp_path / "stderr").open("w") as errors:
            process = subprocess.Popen([str(ROOT / "run.sh"), "--config", str(location)],
                                       stdout=report, stderr=errors)
            fd = None
            received = b""
            dialed = cancelled = False
            invite = None
            try:
                deadline = time.monotonic() + 35
                while time.monotonic() < deadline and process.poll() is None:
                    if fd is None and terminal.exists():
                        fd = os.open(terminal, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
                        os.write(fd, b"AT\r")
                    ready = select.select([peer] + ([fd] if fd is not None else []), [], [], .1)[0]
                    if fd is not None and fd in ready:
                        received += os.read(fd, 8192)
                        if not dialed and b"OK" in received:
                            dialed = True
                            os.write(fd, b"ATDT100\r")
                    if peer in ready:
                        packet, address = peer.recvfrom(8192)
                        if packet.startswith(b"INVITE ") and invite is None:
                            invite = packet
                            values = dict(line.split(": ", 1) for line in packet.decode().split("\r\n")[1:] if ": " in line)
                            response = ("SIP/2.0 180 Ringing\r\n" + "".join(
                                f"{key}: {values[key]}\r\n" for key in ("Via", "From", "To", "Call-ID", "CSeq"))
                                + "Content-Length: 0\r\n\r\n").encode()
                            peer.sendto(response, address)
                            os.write(fd, b"x")
                        elif packet.startswith(b"CANCEL "):
                            cancelled = True
                            break
                assert invite is not None, received
                assert cancelled, received
            finally:
                if fd is not None:
                    os.close(fd)
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            assert process.returncode == 0
            assert not terminal.is_symlink()


@pytest.mark.parametrize("auto_answer", [False, True])
def test_firmware_rings_and_answers_incoming_call(tmp_path, auto_answer):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as peer:
        peer.bind(("127.0.0.1", 0))
        peer.setblocking(False)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reserved:
            reserved.bind(("127.0.0.1", 0))
            sip_port = reserved.getsockname()[1]
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reserved:
            reserved.bind(("127.0.0.1", 0))
            rtp_port = reserved.getsockname()[1]
        config = (ROOT / "courier-emu.ini").read_text()
        config = config.replace("server = 192.168.196.29:5060", "server = 127.0.0.1:9")
        config = config.replace("bind = 0.0.0.0", "bind = 127.0.0.1")
        config = config.replace("port = 5074", f"port = {sip_port}")
        config = config.replace("rtp_port = 4014", f"rtp_port = {rtp_port}")
        location = tmp_path / "modem.ini"
        location.write_text(config)
        terminal = tmp_path / "artifacts/courier-emu.tty"
        body = b"v=0\r\nc=IN IP4 127.0.0.1\r\nm=audio 19000 RTP/AVP 0\r\na=rtpmap:0 PCMU/8000\r\n"
        def request(method, to="<sip:courier@127.0.0.1>"):
            payload = body if method == "INVITE" else b""
            return (f"{method} sip:courier@127.0.0.1 SIP/2.0\r\n"
                    "Via: SIP/2.0/UDP 127.0.0.1;branch=z9hG4bKnative\r\n"
                    f"From: <sip:caller@127.0.0.1>;tag=caller\r\nTo: {to}\r\n"
                    f"Call-ID: native-test\r\nCSeq: 1 {method}\r\n"
                    f"Content-Length: {len(payload)}\r\n\r\n").encode() + payload
        with (tmp_path / "worker.json").open("w") as output, \
                (tmp_path / "stderr").open("w") as errors:
            process = subprocess.Popen([str(ROOT / "run.sh"), "--config", str(location)],
                                       stdout=output, stderr=errors)
            fd = None
            received = b""
            invited = answered = manually_answered = False
            try:
                deadline = time.monotonic() + 35
                while time.monotonic() < deadline and process.poll() is None:
                    if fd is None and terminal.exists():
                        fd = os.open(terminal, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
                        os.write(fd, b"ATS0=1\r" if auto_answer else b"ATS0=0\r")
                    ready = select.select([peer] + ([fd] if fd is not None else []), [], [], .1)[0]
                    if fd is not None and fd in ready:
                        received += os.read(fd, 8192)
                        if not invited and b"OK" in received:
                            invited = True
                            peer.sendto(request("INVITE"), ("127.0.0.1", sip_port))
                        if not auto_answer and not manually_answered and b"RING" in received:
                            manually_answered = True
                            os.write(fd, b"ATA\r")
                    if peer in ready:
                        packet, address = peer.recvfrom(8192)
                        if packet.startswith(b"SIP/2.0 200 "):
                            values = dict(line.split(": ", 1) for line in packet.decode().split("\r\n")[1:] if ": " in line)
                            peer.sendto(request("ACK", values["To"]), address)
                            answered = True
                            break
                assert b"RING" in received, received
                assert answered, received
            finally:
                if fd is not None:
                    os.close(fd)
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            assert process.returncode == 0
            assert not terminal.is_symlink()
