"""Passive, batched views of native mailbox diagnostics.

Reading or ignoring these views never services a mailbox or changes device
state. Records and summaries are copied only when a host caller asks for them.
"""
import ctypes as c
from collections.abc import Mapping, Sequence


class ObserverState(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in ('words', 'history_count',
        'history_overwritten', 'summary_count', 'summary_overflow', 'history_enabled')]


class Record(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in ('sequence', 'instructions', 'pc', 'header', 'data')]


class Summary(c.Structure):
    _fields_ = [(name, c.c_uint64) for name in ('key', 'count', 'instructions', 'pc', 'order')]


class NativeMailboxObserver:
    def __init__(self, owner, bind):
        self.owner = owner
        self.state.history_enabled = 1
        self._snapshot = bind('observer', c.c_size_t, c.c_void_p, c.c_uint, c.c_void_p, c.c_size_t)
        self._record = bind('record', None, c.c_void_p, c.c_uint, c.c_uint, c.c_uint64, c.c_uint64)
        self._final = None
        self.messages = MessageHistory(self)
        self.counts = MessageCounts(self)

    @property
    def state(self): return self.owner.state.observer

    @property
    def enabled(self): return bool(self.state.history_enabled)

    @enabled.setter
    def enabled(self, value): self.state.history_enabled = bool(value)

    def rows(self, kind):
        if self._final is not None: return self._final[kind]
        count = self._snapshot(self.owner.handle, kind, None, 0)
        rows = ((Summary if kind else Record) * count)()
        self._snapshot(self.owner.handle, kind, rows, count)
        return sorted(rows, key=lambda row: row.order) if kind else list(rows)

    def records(self):
        """Return a batch with sequence numbers so observers can detect gaps."""
        return [dict(sequence=row.sequence, instructions=row.instructions,
                     pc=None if row.pc == (1 << 64) - 1 else row.pc,
                     header=row.header, data=row.data) for row in self.rows(0)]

    @property
    def first_seen(self): return {key(row.key): row.instructions for row in self.rows(1)}

    @property
    def first_pc(self):
        return {key(row.key): f'{row.pc:05x}' for row in self.rows(1) if row.pc != (1 << 64) - 1}

    def record(self, words, instructions, pc):
        self._record(self.owner.handle, words[0], words[1], instructions,
                     (1 << 64) - 1 if pc is None else pc)

    def close(self):
        if self._final is None: self._final = self.rows(0), self.rows(1)


def key(value): return f'{value >> 16:04x}:{value & 65535:04x}'


class MessageHistory(Sequence):
    def __init__(self, observer): self.observer = observer
    def __len__(self): return self.observer.state.history_count
    def __iter__(self): return (f'{row.header:04x}:{row.data:04x}' for row in self.observer.rows(0))
    def __getitem__(self, index): return list(self)[index]


class MessageCounts(Mapping):
    def __init__(self, observer):
        self.observer = observer
        self._words, self._counts = -1, {}
    def _values(self):
        words = self.observer.state.words
        if self._words != words:
            self._counts = {key(row.key): row.count for row in self.observer.rows(1)}
            self._words = words
        return self._counts
    def __len__(self): return self.observer.state.summary_count
    def __iter__(self): return iter(self._values())
    def __getitem__(self, message): return self._values().get(message, 0)
    def __contains__(self, message): return message in self._values()
    def get(self, message, default=None): return self._values().get(message, default)
    def items(self): return self._values().items()
    def values(self): return self._values().values()
    def most_common(self, n=None):
        if n is not None and n <= 0: return []
        return sorted(self.items(), key=lambda item: -item[1])[:n]
