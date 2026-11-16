"""Focused checks for native terminal byte I/O and output backpressure."""
import os
import socket

import pytest

from courier_emu.console import SerialConsole, MAX_PENDING_OUTPUT
from courier_emu.console_native import NativeSerialConsole


@pytest.mark.parametrize('native', [False, True])
def test_terminal_bidirectional_bytes_eof_and_counts(native):
    local, remote = socket.socketpair()
    console = SerialConsole(local.detach())
    if native:
        assert NativeSerialConsole.adopt(console) is console
    try:
        remote.sendall(b'AT\r')
        assert console.wait(0)
        assert console.poll(1) == b'A'
        assert console.poll() == b'T\r'
        assert console.poll() == b''
        for byte in b'OK\r\n':
            console.write(byte)
        assert remote.recv(4) == b'OK\r\n'
        remote.shutdown(socket.SHUT_WR)
        assert console.poll() == b'' and console.closed
        assert console.summary() == dict(received=3, sent=4, dropped=0, pending=0, closed=True)
    finally:
        console.close()
        remote.close()


@pytest.mark.parametrize('native', [False, True])
def test_terminal_bounded_output_when_peer_stops_reading(native):
    local, remote = socket.socketpair()
    local.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    console = SerialConsole(local.detach())
    if native:
        NativeSerialConsole.adopt(console)
    try:
        while True:
            try:
                os.write(console.fd, b'x' * 4096)
            except BlockingIOError:
                break
        for _ in range(MAX_PENDING_OUTPUT + 7):
            console.write(0x55)
        status = console.summary()
        assert status['pending'] == MAX_PENDING_OUTPUT and status['dropped'] == 7
        assert status['sent'] == 0 and not status['closed']
    finally:
        console.close()
        remote.close()
