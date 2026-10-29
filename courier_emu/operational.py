"""Bounded live logs that exclude the serial application stream."""
from collections import deque
import logging
import logging.handlers
import queue
import re
import sys
import threading

LOG = logging.getLogger('courier_emu')
LOG.addHandler(logging.NullHandler())
LOG.propagate = False


class EventLog(deque):
    def append(self, value):
        super().append(value)
        LOG.log(logging.DEBUG if 'retransmit' in value else logging.INFO,
                '[sip] %s', value)


class OperationalLog:
    """The bounded queue never waits for stderr on the modem thread."""
    def __init__(self, level, stream=None):
        self.queue = queue.Queue(maxsize=256)
        self.stopped = threading.Event()
        self.dropped = 0
        self.stream = stream if stream is not None else sys.stderr
        owner = self
        class Handler(logging.handlers.QueueHandler):
            def enqueue(self, record):
                try:
                    self.queue.put_nowait(record)
                except queue.Full:
                    owner.dropped += 1
        self.handler = Handler(self.queue)
        self.previous = LOG.level
        LOG.setLevel({'quiet': logging.WARNING, 'normal': logging.INFO,
                      'debug': logging.DEBUG}[level])
        LOG.addHandler(self.handler)
        self.thread = threading.Thread(target=self._write, name='courier-log', daemon=True)
        self.thread.start()

    def _write(self):
        formatter = logging.Formatter('[%(levelname)s] %(message)s')
        while not self.stopped.is_set() or not self.queue.empty():
            try:
                record = self.queue.get(timeout=.05)
            except queue.Empty:
                continue
            try:
                if self.dropped:
                    count, self.dropped = self.dropped, 0
                    self.stream.write(f'[WARNING] [log] discarded {count} queued messages\n')
                self.stream.write(formatter.format(record) + '\n')
                self.stream.flush()
            except (OSError, ValueError):
                return

    def close(self):
        LOG.removeHandler(self.handler)
        LOG.setLevel(self.previous)
        self.stopped.set()
        self.thread.join(timeout=1)


class AtEvents:
    def __init__(self):
        self.input = bytearray()
        self.output = bytearray()

    def received(self, byte, *, command_mode):
        if not command_mode:
            self.input.clear()
            return
        byte &= 0x7f
        if byte in (10, 13):
            line = bytes(self.input)
            self.input.clear()
            if line[:2].upper() == b'AT':
                LOG.info('[at] command: %r', line.decode('ascii', 'backslashreplace'))
        elif byte in (8, 127):
            if self.input:
                self.input.pop()
        elif len(self.input) < 1024:
            self.input.append(byte)
        else:
            self.input.clear()

    def transmitted(self, byte, *, command_mode):
        # A CONNECT line can finish after the callback enters data mode.
        if not command_mode and not self.output.startswith(b'CONNECT'):
            self.output.clear()
            return
        byte &= 0x7f
        if byte in (10, 13):
            line = bytes(self.output)
            self.output.clear()
            if re.fullmatch(rb'(?:CONNECT(?: [ -~]*)?|OK|ERROR|NO CARRIER|'
                            rb'NO DIAL TONE|BUSY|NO ANSWER|RING|RINGING)', line):
                LOG.info('[at] result: %s', line.decode('ascii'))
        elif len(self.output) < 1024:
            self.output.append(byte)
        else:
            self.output.clear()
