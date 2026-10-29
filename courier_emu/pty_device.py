"""Publish a locked, stable name for a process-owned serial PTY."""
from __future__ import annotations

import fcntl
import os
from pathlib import Path


class PtyDevice:
    def __init__(self, path: str | None):
        self.path = Path(path).absolute() if path else None
        self.target = None
        self.lock = None

    def __enter__(self):
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.lock = open(str(self.path) + ".lock", "a")
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if self.path.exists() and not self.path.is_symlink():
                    raise ValueError(f"refusing to replace a non-symlink: {self.path}")
            except (OSError, ValueError) as exc:
                self.lock.close()
                self.lock = None
                raise ValueError(f"cannot publish terminal {self.path}: {exc}") from exc
        return self

    def publish(self, target: str):
        if self.path is not None:
            # The lock is held across publication, the worker lifetime, and
            # cleanup. A second launcher cannot steal an active terminal.
            if self.path.is_symlink():
                self.path.unlink()
            self.path.symlink_to(target)
            self.target = target

    def __exit__(self, *exc):
        try:
            if (self.path is not None and self.target is not None
                    and self.path.is_symlink() and os.readlink(self.path) == self.target):
                self.path.unlink()
        finally:
            if self.lock is not None:
                self.lock.close()
        # Keep the lock file: unlinking it can let two processes lock
        # different inodes under the same name.
