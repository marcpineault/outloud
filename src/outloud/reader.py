"""The reading loop.

Speaks chunks one at a time on a worker thread and reports progress through a
queue the UI polls. Pause and jump work by killing the current utterance; the
interrupted sentence is spoken again from its start on resume, which is what a
listener expects.

Events put on the queue (tuples):
    ("chunk", i)     about to speak chunk i
    ("paused", i)    paused before chunk i
    ("resumed", i)
    ("finished",)    ran off the end
    ("stopped", i)   stop() was called
    ("error", msg)
"""
from __future__ import annotations

import queue
import threading
import time
from typing import List, Optional

from .textsplit import Chunk
from .tts import Backend


class Reader:
    def __init__(self, backend: Backend, events: "queue.Queue") -> None:
        self.backend = backend
        self.events = events
        self.voice: Optional[str] = None
        self.rate: int = 180
        self.state = "idle"  # idle | playing | paused
        self._chunks: List[Chunk] = []
        self._index = 0
        self._jump: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._pause = threading.Event()

    # -- what to read -------------------------------------------------------
    def load(self, chunks: List[Chunk]) -> None:
        self.stop()
        self._chunks = list(chunks)
        self._index = 0

    @property
    def chunks(self) -> List[Chunk]:
        return self._chunks

    @property
    def index(self) -> int:
        return self._index

    # -- transport ------------------------------------------------------------
    def play(self, index: Optional[int] = None) -> None:
        if not self._chunks:
            return
        if index is not None:
            index = max(0, min(index, len(self._chunks) - 1))
        if self.state == "playing":
            if index is not None:
                self._jump = index
                self.backend.stop()
            return
        if self.state == "paused":
            if index is not None:
                self._jump = index
            self.state = "playing"
            self._pause.clear()
            return
        if index is not None:
            self._index = index
        old = self._thread
        if old is not None and old.is_alive():
            old.join(timeout=2)
        self._stop.clear()
        self._pause.clear()
        self._jump = None
        self.state = "playing"
        self._thread = threading.Thread(target=self._run, name="outloud-reader", daemon=True)
        self._thread.start()

    def pause(self) -> None:
        if self.state != "playing":
            return
        self.state = "paused"
        self._pause.set()
        self.backend.stop()

    def toggle(self) -> None:
        if self.state == "playing":
            self.pause()
        else:
            self.play()

    def seek(self, delta: int) -> None:
        self.play(self._index + delta)

    def stop(self) -> None:
        t = self._thread
        if t is not None and t.is_alive():
            self._stop.set()
            self._pause.clear()
            self.backend.stop()
            if t is not threading.current_thread():
                t.join(timeout=3)
        self._thread = None
        self.state = "idle"

    # -- worker -----------------------------------------------------------------
    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                if self._pause.is_set():
                    self.events.put(("paused", self._index))
                    while self._pause.is_set() and not self._stop.is_set():
                        time.sleep(0.05)
                    if self._stop.is_set():
                        break
                    self.events.put(("resumed", self._index))
                if self._jump is not None:
                    self._index, self._jump = self._jump, None
                if self._index >= len(self._chunks):
                    self.state = "idle"
                    self.events.put(("finished",))
                    return
                chunk = self._chunks[self._index]
                self.events.put(("chunk", self._index))
                self.backend.speak(chunk.text, self.voice, self.rate)
                if self._stop.is_set() or self._pause.is_set() or self._jump is not None:
                    continue  # interrupted: do not advance
                self._index += 1
            self.state = "idle"
            self.events.put(("stopped", self._index))
        except Exception as exc:  # surfaced in the UI, never silent
            self.state = "idle"
            self.events.put(("error", str(exc)))
