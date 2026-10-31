"""Serialsim modem (pipe-B) transport, including the peer's UART signals.

DSR currently means that the Courier endpoint is attached and running. The
board ASIC's firmware-driven DSR output is not yet decoded by this emulator.
"""
import array
import fcntl
import termios
import tty

from .console import SerialConsole

SET_REMOTE_NULL_MODEM = 0x54E4
GET_REMOTE_CONTROL = 0x800454E9  # _IOR('T', 0xe9, unsigned int), Linux


class SerialSimConsole(SerialConsole):
    serialsim = True

    def __init__(self, fd, **kwargs):
        super().__init__(fd, **kwargs)
        self._released = False
        self.dsr = False
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.dtr = False
        self._read_control()  # Reject ordinary PTYs or other device types.
        tty.setraw(fd)
        attrs = termios.tcgetattr(fd)
        attrs[2] |= termios.CLOCAL | termios.CREAD | termios.HUPCL
        attrs[4] = attrs[5] = termios.B115200
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        # Use this FD's DTR as the modem's DSR output. The kernel crosses it
        # to the peer's DSR, and HUPCL also drops it if the worker is killed.
        fcntl.ioctl(fd, SET_REMOTE_NULL_MODEM, 1)
        self._dsr(True)

    def _read_control(self):
        value = array.array('I', [0])
        fcntl.ioctl(self.fd, GET_REMOTE_CONTROL, value, True)
        self.dtr = bool(value[0] & termios.TIOCM_DTR)

    def _dsr(self, asserted):
        fcntl.ioctl(self.fd, termios.TIOCMBIS if asserted else termios.TIOCMBIC,
                    array.array('I', [termios.TIOCM_DTR]))
        self.dsr = asserted

    def poll(self, limit=4096):
        self._read_control()
        return super().poll(limit)

    def close(self):
        if self._released:
            return
        try:
            self._dsr(False)
        finally:
            super().close()
            self._released = True

    def summary(self):
        return {**super().summary(), 'backend': 'serialsim',
                'dtr': self.dtr, 'dsr_endpoint_ready': self.dsr}
