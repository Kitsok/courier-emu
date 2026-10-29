import io
import threading
from courier_emu.operational import AtEvents, LOG, OperationalLog


def test_normal_logs_commands_and_complete_connect_but_not_payload():
    stream = io.StringIO()
    logs = OperationalLog('normal', stream)
    events = AtEvents()
    try:
        for byte in b'atdt100\r':
            events.received(byte, command_mode=True)
        for byte in b'\r\nCONNECT':
            events.transmitted(byte, command_mode=True)
        for byte in b' 31200/ARQ/V34/LAPM/V42BIS\r\n':
            events.transmitted(byte, command_mode=False)
        for byte in b'ATsecret\r':
            events.received(byte, command_mode=False)
            events.transmitted(byte, command_mode=False)
        for byte in b'\r\nNO CARRIER\r\n':
            events.transmitted(byte, command_mode=True)
    finally:
        logs.close()
    text = stream.getvalue()
    assert "command: 'atdt100'" in text
    assert 'CONNECT 31200/ARQ/V34/LAPM/V42BIS' in text
    assert 'NO CARRIER' in text
    assert 'secret' not in text


def test_quiet_filters_at_results_and_debug():
    stream = io.StringIO()
    logs = OperationalLog('quiet', stream)
    try:
        LOG.info('[at] result: OK')
        LOG.debug('internal diagnostics')
        LOG.warning('call failed')
    finally:
        logs.close()
    assert stream.getvalue() == '[WARNING] call failed\n'


def test_blocked_stderr_cannot_block_modem_log_producer():
    entered, release = threading.Event(), threading.Event()
    class Blocked(io.StringIO):
        def write(self, text):
            entered.set()
            release.wait(3)
            return super().write(text)
    stream = Blocked()
    logs = OperationalLog('debug', stream)
    try:
        LOG.info('first')
        assert entered.wait(1)
        for _ in range(1000):
            LOG.debug('DSP event')
        assert logs.queue.qsize() <= 256
        assert logs.dropped > 0
    finally:
        release.set()
        logs.close()
