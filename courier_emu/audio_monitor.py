"""Optional desktop playback of the firmware speaker, outside modem timing."""
from __future__ import annotations

import os
import queue
import select
import shutil
import struct
import subprocess
import threading
import time

from .operational import LOG


class AudioMonitor:
    def __init__(self, volume=.25, *, player=None):
        self.volume = volume
        self.player = player if player is not None else shutil.which('paplay')
        self.frames = queue.Queue(maxsize=10)  # at most 200 ms of monitor audio
        self.stopped = threading.Event()
        self.generation = 0
        self.enabled = False
        self.disabled = not bool(self.player)
        if self.disabled:
            LOG.warning('[speaker] paplay is unavailable; local playback disabled')
        self.thread = threading.Thread(target=self._run, name='courier-speaker', daemon=True)
        self.thread.start()

    def feed(self, tx, rx, *, enabled):
        if enabled != self.enabled:
            self.enabled = enabled
            self.generation += 1
        if not enabled or self.disabled or self.stopped.is_set():
            return
        for start in range(0, min(len(tx), len(rx)), 160):
            frame = (self.generation, tuple(tx[start:start+160]), tuple(rx[start:start+160]))
            try:
                self.frames.put_nowait(frame)
            except queue.Full:
                # Playback is best effort. Retain current audio, not backlog.
                try:
                    self.frames.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self.frames.put_nowait(frame)
                except queue.Full:
                    pass

    @staticmethod
    def _close_player(process):
        if process is None:
            return
        process.stdin.close()
        try:
            process.wait(timeout=.2)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=.2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    def _run(self):
        if self.disabled:
            return
        process = None
        generation = -1
        try:
            while not self.stopped.is_set():
                if process is not None and generation != self.generation:
                    self._close_player(process)
                    process = None
                try:
                    frame_generation, tx, rx = self.frames.get(timeout=.02)
                except queue.Empty:
                    continue
                if not self.enabled or frame_generation != self.generation:
                    continue
                if process is None:
                    process = subprocess.Popen(
                        [self.player, '--raw', '--format=s16le', '--rate=8000',
                         '--channels=1', '--latency-msec=60',
                         '--client-name=courier-emu', '--stream-name=Courier speaker'],
                        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, bufsize=0)
                    os.set_blocking(process.stdin.fileno(), False)
                    generation = frame_generation
                if process.poll() is not None:
                    raise OSError('audio player exited')
                values = [max(-32768, min(32767, round((a+b)*self.volume)))
                          for a,b in zip(tx, rx)]
                pending = memoryview(struct.pack("<"+"h"*len(values), *values))
                deadline = time.monotonic()+.1
                while pending and not self.stopped.is_set():
                    if generation != self.generation or time.monotonic() >= deadline:
                        break
                    if select.select([], [process.stdin], [], .02)[1]:
                        try:
                            pending = pending[os.write(process.stdin.fileno(), pending):]
                        except BlockingIOError:
                            pass
                if pending:
                    self._close_player(process)
                    process = None
        except (OSError, ValueError) as exc:
            self.disabled = True
            LOG.warning('[speaker] playback failed: %s; modem continues', exc)
        finally:
            self._close_player(process)

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=1)
