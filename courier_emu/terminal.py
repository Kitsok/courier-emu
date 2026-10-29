"""The terminal side of a live console session.

The emulation runs in the worker child process, so the byte channel that
`SerialConsole` reads and writes has to reach it as an inherited descriptor.
This module makes that channel and either drives it from the launching
terminal (`--console`) or hands it out as a device node for another program to
open (`--serial-pty`).
"""

from __future__ import annotations

import argparse
import json
import os
import select
import shutil
import signal
import socket
import subprocess
import sys
from typing import TextIO
from .pty_device import PtyDevice

# Ctrl-] , as in telnet: raw mode passes everything else through to the
# firmware, including Ctrl-C, which a modem is entitled to receive.
DETACH_BYTE = 0x1D
POLL_SECONDS = 0.05
# Long enough for the worker to leave its emulation loop and serialize a
# result, short enough that a wedged child does not hold the terminal.
SHUTDOWN_SECONDS = 10.0


def _pty_channel() -> tuple[int, int, str]:
    """Return (worker end, terminal end, device path) for a pty pair.

    The worker holds the master so that whoever opens the slave path speaks
    to the firmware. Raw mode keeps the line discipline from echoing bytes or
    rewriting the carriage returns the AT parser terminates on.
    """
    import pty
    import tty

    master, slave = pty.openpty()
    tty.setraw(slave)
    return master, slave, os.ttyname(slave)


def run_console(
    args: argparse.Namespace, command: list[str], environment: dict[str, str]
) -> int:
    with PtyDevice(getattr(args, "serial_link", None)) as device:
        return _run_console(args, command, environment, device)


def _run_console(args, command, environment, publication) -> int:
    if args.console and args.serial_pty:
        raise ValueError("use --console or --serial-pty, not both")

    keep_open: int | None = None
    lamps_read: int | None = None
    lamps_write: int | None = None
    if args.serial_pty:
        worker_end, keep_open, device = _pty_channel()
        publication.publish(device)
        terminal: socket.socket | None = None
    else:
        left, right = socket.socketpair()
        worker_end, terminal, device = right.fileno(), left, ""
        # The lamps get the terminal's bottom line, which only means something
        # when stdout is a terminal; a redirected session stays byte-exact.
        if sys.stdout.isatty():
            lamps_read, lamps_write = os.pipe()

    extra = ["--serial-fd", str(worker_end)]
    passed = [worker_end]
    if lamps_write is not None:
        extra += ["--lamps-fd", str(lamps_write)]
        passed.append(lamps_write)
    operational = bool(getattr(args, "log_level", None))
    process = subprocess.Popen(
        command + extra,
        pass_fds=tuple(passed),
        stdout=subprocess.DEVNULL if operational else subprocess.PIPE,
        stderr=None if operational else subprocess.PIPE,
        text=True,
        env=environment,
    )
    # The worker owns its end now; holding a second copy open here would keep
    # the channel from ever reporting that the far side has gone.
    if args.serial_pty:
        os.close(worker_end)
    else:
        right.close()
    if lamps_write is not None:
        os.close(lamps_write)

    captured: tuple[str, str] | None = None
    try:
        if args.serial_pty:
            print(f"serial console on {device}", file=sys.stderr)
            print(f"attach with: tio {publication.path or device}", file=sys.stderr)
            print("stop with: Ctrl-C here", file=sys.stderr, flush=True)
            _forward_termination(process)
            # communicate() rather than wait(): the worker's result can be
            # larger than a pipe buffer, and nothing would be draining it.
            captured = process.communicate()
        else:
            assert terminal is not None
            _drive_terminal(terminal, process, lamps_read)
    except KeyboardInterrupt:
        # Nothing has closed the channel, so ask the run to wind itself up
        # rather than waiting out the shutdown timeout.
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
    finally:
        if terminal is not None:
            terminal.close()
        if keep_open is not None:
            os.close(keep_open)
        if lamps_read is not None:
            os.close(lamps_read)

    if operational:
        if process.poll() is None:
            try:
                process.wait(timeout=SHUTDOWN_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        return 0 if process.returncode == 0 else 2

    # In a terminal session stdout is the modem, so the run's own report goes
    # to stderr and `--console > session.txt` captures exactly what the
    # firmware said. A pty session leaves stdout free for the report itself.
    return _finish(
        process,
        summary=args.summary,
        stream=sys.stdout if args.serial_pty else sys.stderr,
        captured=captured,
    )


def _forward_termination(process: subprocess.Popen[str]) -> None:
    """Pass a termination signal on, so the run still reports itself."""

    def handler(*_: object) -> None:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)

    signal.signal(signal.SIGTERM, handler)


class LampLine:
    """The front-panel lamps, held on the terminal's bottom row.

    A scroll region over every row but the last keeps the firmware's output
    scrolling above it; each redraw saves the cursor, paints the last row, and
    puts the cursor back, so the serial stream never sees it.
    """

    LIT = "\x1b[1;31m"   # Courier lamps are red
    DIM = "\x1b[2m"
    RESET = "\x1b[0m"

    def __init__(self, fd: int) -> None:
        self.fd = fd
        self.rows = 0
        self.line = ""

    def _write(self, text: str) -> None:
        os.write(self.fd, text.encode())

    def _reserve(self) -> None:
        rows = shutil.get_terminal_size().lines
        if rows == self.rows or rows < 2:
            return
        # A newline first, so a cursor already on the last row is lifted
        # into the region rather than left under the lamps.
        self._write(f"\n\x1b[1A\x1b7\x1b[1;{rows - 1}r\x1b8")
        self.rows = rows

    def show(self, line: str) -> None:
        self.line = line
        self._reserve()
        if not self.rows:
            return
        parts = []
        for token in line.split():
            if token.strip(".?"):
                parts.append(f"{self.LIT}{token}{self.RESET}")
            else:
                parts.append(f"{self.DIM}{token}{self.RESET}")
        self._write(f"\x1b7\x1b[{self.rows};1H\x1b[2K {'  '.join(parts)}\x1b8")

    def refresh(self) -> None:
        """Redraw after a resize, which resets nothing on its own."""
        if self.line and shutil.get_terminal_size().lines != self.rows:
            self.show(self.line)

    def close(self) -> None:
        if not self.rows:
            return
        self._write(f"\x1b7\x1b[r\x1b[{self.rows};1H\x1b[2K\x1b8")
        self.rows = 0


def _drive_terminal(
    terminal: socket.socket,
    process: subprocess.Popen[str],
    lamps_fd: int | None = None,
) -> None:
    """Shuttle bytes between this terminal and the modelled DTE."""
    raw = sys.stdin.isatty()
    lamps = LampLine(sys.stdout.fileno()) if lamps_fd is not None else None
    pending = b""
    if raw:
        import termios
        import tty

        saved = termios.tcgetattr(sys.stdin)
        print(
            "console attached; type AT commands, Ctrl-] to detach",
            file=sys.stderr,
            flush=True,
        )
        tty.setraw(sys.stdin)
    stdin_open = True
    try:
        while process.poll() is None:
            watched: list = [terminal]
            if stdin_open:
                watched.append(sys.stdin)
            if lamps_fd is not None:
                watched.append(lamps_fd)
            readable, _, _ = select.select(watched, [], [], POLL_SECONDS)
            if lamps is not None:
                if lamps_fd in readable:
                    chunk = os.read(lamps_fd, 4096)
                    if not chunk:
                        lamps_fd = None
                    pending += chunk
                    # Only the newest complete line matters.
                    if b"\n" in pending:
                        complete, _, pending = pending.rpartition(b"\n")
                        latest = complete.rpartition(b"\n")[2]
                        lamps.show(latest.decode("ascii", "replace"))
                lamps.refresh()
            if sys.stdin in readable:
                typed = os.read(sys.stdin.fileno(), 1024)
                if not typed:
                    # A pipe has delivered everything it holds. A terminal
                    # reports the same on Ctrl-D, and either way there is no
                    # more input; keep printing what the firmware says.
                    stdin_open = False
                elif DETACH_BYTE in typed:
                    terminal.sendall(typed[: typed.index(DETACH_BYTE)])
                    break
                else:
                    terminal.sendall(typed)
            if terminal in readable:
                received = terminal.recv(4096)
                if not received:
                    break
                os.write(sys.stdout.fileno(), received)
    finally:
        if lamps is not None:
            lamps.close()
        if raw:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, saved)
            print(file=sys.stderr)


def _finish(
    process: subprocess.Popen[str],
    *,
    summary: bool,
    stream: TextIO,
    captured: tuple[str, str] | None = None,
) -> int:
    """Close the session down and report what the run recorded."""
    if captured is not None:
        stdout, stderr = captured
    else:
        try:
            stdout, stderr = process.communicate(timeout=SHUTDOWN_SECONDS)
        except subprocess.TimeoutExpired:
            process.send_signal(signal.SIGTERM)
            try:
                stdout, stderr = process.communicate(timeout=SHUTDOWN_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
    if process.returncode not in (0, -signal.SIGTERM):
        detail = (stderr or "").strip() or (stdout or "").strip()
        print(f"execution worker failed (exit {process.returncode})", file=sys.stderr)
        if detail:
            print(detail, file=sys.stderr)
        return 2
    if not (stdout or "").strip():
        return 0
    result = json.loads(stdout)
    if summary:
        result.pop("io_events", None)
        result.pop("mmio_events", None)
        result.pop("last_addresses", None)
    print(json.dumps(result, indent=2, sort_keys=True), file=stream)
    return 0
