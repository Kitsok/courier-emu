"""Exercise command echo through a raw PTY with terminal echo disabled."""
import os
from pathlib import Path
import select
import socket
import subprocess
import time
from types import SimpleNamespace

from courier_emu.machine import CourierMachine


ROOT = Path(__file__).resolve().parent.parent


def test_command_echo_never_returns_online_payload_or_script_input():
    emitted = []
    machine = SimpleNamespace(console=SimpleNamespace(write=emitted.append),
                              _firmware_command_mode=lambda: False,
                              _rom_serial=SimpleNamespace(echo_setting=0x4d5),
                              _capture_serial=emitted.append)
    memory = SimpleNamespace(mem_read=lambda address, size: b'\x01')
    CourierMachine._echo_command_byte(machine, memory, ord('x'))
    assert emitted == []
    machine._firmware_command_mode = lambda: True
    CourierMachine._echo_command_byte(machine, memory, ord('x'))
    assert emitted == [ord('x')]
    emitted.clear()
    machine.console = None
    CourierMachine._echo_command_byte(machine, memory, ord('x'))
    assert emitted == []


def test_analog_firmware_echo_setting_controls_each_character(tmp_path):
    config = (ROOT / 'courier-emu.ini').read_text()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sip, \
            socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as rtp:
        sip.bind(('127.0.0.1', 0))
        rtp.bind(('127.0.0.1', 0))
        config = config.replace('port = 5074', f'port = {sip.getsockname()[1]}')
        config = config.replace('rtp_port = 4014', f'rtp_port = {rtp.getsockname()[1]}')
    config = config.replace('192.168.196.29', '127.0.0.1')
    config = config.replace('0.0.0.0', '127.0.0.1')
    location = tmp_path / 'modem.ini'
    location.write_text(config)
    terminal = tmp_path / 'artifacts/courier-emu.tty'
    with (tmp_path / 'log').open('w') as log:
        process = subprocess.Popen([str(ROOT / 'run.sh'), '--config', str(location)],
                                   stdout=log, stderr=log)
        fd = None
        def read_until(token, timeout=10):
            data = b''
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if select.select([fd], [], [], .05)[0]:
                    data += os.read(fd, 8192)
                    if token in data:
                        return data
            raise AssertionError((token, data, (tmp_path / 'log').read_text()))

        def command(text):
            os.write(fd, text + b'\r')
            return read_until(b'OK\r\n')

        try:
            deadline = time.monotonic() + 15
            while not terminal.exists() and time.monotonic() < deadline:
                time.sleep(.05)
            fd = os.open(terminal, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            command(b'AT')
            command(b'ATE1')
            # Echo must arrive while typing, before CR executes the command.
            os.write(fd, b'ATI3')
            assert read_until(b'ATI3') == b'ATI3'
            os.write(fd, b'\r')
            response = read_until(b'OK\r\n')
            assert b'Courier' in response
            assert b'ATI3' not in response  # no delayed or duplicate echo
            command(b'ATE0')
            assert command(b'ATI3') == b'\r\nUSRobotics Courier V.Everything\r\n\r\nOK\r\n'
            command(b'ATE1')
            assert command(b'AT') == b'AT\r\r\nOK\r\n'
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            if fd is not None:
                os.close(fd)
