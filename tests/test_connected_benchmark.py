"""Exercise the benchmark verifier through real binary sockets, without modems."""
import os
import select
import socket
import time

import pytest

from tools.benchmark_connected import ROLES, transfer


class SocketPair:
    def __init__(self, output, corrupt=False):
        self.output, self.corrupt = output, corrupt
        self.sockets = socket.socketpair()
        for sock in self.sockets:
            sock.setblocking(False)
        self.fds = dict(zip(ROLES, (s.fileno() for s in self.sockets)))
        self.transcripts = {r: bytearray() for r in ROLES}
        for role in ROLES:
            (output/role).mkdir()

    def cpu(self):
        return dict.fromkeys(ROLES, time.process_time())

    def poll(self, timeout):
        ready = select.select(list(self.fds.values()), [], [], timeout)[0]
        for role, fd in self.fds.items():
            if fd in ready:
                chunk = os.read(fd, 8192)
                if self.corrupt and chunk:
                    chunk = bytes([chunk[0] ^ 1]) + chunk[1:]
                    self.corrupt = False
                self.transcripts[role].extend(chunk)

    def close(self):
        for sock in self.sockets:
            sock.close()


@pytest.mark.parametrize('payload', ['binary', 'printable'])
def test_connected_benchmark_verifies_both_binary_streams(tmp_path, payload):
    pair = SocketPair(tmp_path)
    try:
        result = transfer(pair, .06, dict.fromkeys(ROLES, 10000), 1, payload=payload)
        assert result['window_wall_seconds'] >= .06
        for i, role in enumerate(ROLES):
            peer = ROLES[1-i]
            assert result['received_bytes'][role] == result['sent_bytes'][peer] > 0
            assert result['received_sha256'][role] == result['sent_sha256'][peer]
    finally:
        pair.close()


def test_connected_benchmark_rejects_corrupted_data(tmp_path):
    pair = SocketPair(tmp_path, corrupt=True)
    try:
        with pytest.raises(RuntimeError, match='payload mismatch'):
            transfer(pair, .06, dict.fromkeys(ROLES, 10000), 1)
    finally:
        pair.close()


def test_connected_benchmark_rejects_an_empty_data_window(tmp_path):
    pair = SocketPair(tmp_path)
    try:
        with pytest.raises(RuntimeError, match='no payload transferred'):
            transfer(pair, .01, dict.fromkeys(ROLES, 0), 1)
    finally:
        pair.close()
