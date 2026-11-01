"""Short, input-aware scheduler waits on instruction or SIP media clocks."""
import math
import time


class InstructionPacer:
    def __init__(self, *, clock=None, interval=0.005):
        self.clock = clock or time.monotonic
        self.interval = interval
        self.next_check = 0
        self.origin = None
        self.rate = 0
        self.waits = self.wakeups = 0
        self.waited = 0.0

    def service(self, instructions, rate, *, idle, reset, wait):
        """Wait only for positive lead; readable input ends a wait early.

        Native polling must hand back by next_check. Work behind the wall
        clock is never slowed, and no guest cycles are skipped by a wait.
        """
        self.next_check = instructions + max(1, math.ceil(rate * self.interval))
        if reset or rate != self.rate:
            self.origin = None
        self.rate = rate
        if not idle:
            return False
        now = self.clock()
        if self.origin is None:
            self.origin = instructions, now
            return False
        count, wall = self.origin
        delay = min(self.interval, wall + (instructions - count) / rate - now)
        if delay <= 0:
            return False
        self.waits += 1
        readable = bool(wait(delay))
        self.waited += max(0.0, self.clock() - now)
        self.wakeups += readable
        return readable

    def summary(self):
        return {"waits": self.waits, "input_wakeups": self.wakeups,
                "waited_seconds": self.waited}


class DeadlinePacer(InstructionPacer):
    """A scheduler check driven by an external media timeline."""

    def service(self, instructions, rate, *, deadline, wait):
        self.next_check = instructions + max(1, math.ceil(rate * self.interval))
        if deadline is None:
            return False
        now = self.clock()
        delay = min(self.interval, deadline - now)
        if delay <= 0:
            return False
        self.waits += 1
        readable = bool(wait(delay))
        self.waited += max(0.0, self.clock() - now)
        self.wakeups += readable
        return readable
