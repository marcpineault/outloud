import queue
import threading
import time

from outloud.reader import Reader
from outloud.textsplit import Chunk
from outloud.tts import Backend


class FakeBackend(Backend):
    name = "fake"

    def __init__(self, per_chunk=0.05):
        self.spoken = []
        self.per_chunk = per_chunk
        self._interrupt = threading.Event()

    def speak(self, text, voice, rate_wpm):
        self.spoken.append(text)
        self._interrupt.clear()
        self._interrupt.wait(self.per_chunk)

    def stop(self):
        self._interrupt.set()


def _chunks(n):
    return [Chunk(f"s{i}", i * 3, i * 3 + 2) for i in range(n)]


def _drain(q, timeout=2.0):
    out, deadline = [], time.time() + timeout
    while time.time() < deadline:
        try:
            ev = q.get(timeout=0.05)
            out.append(ev)
            if ev[0] in ("finished", "stopped", "error"):
                break
        except queue.Empty:
            pass
    return out


def test_plays_all_chunks_in_order_then_finishes():
    q = queue.Queue()
    r = Reader(FakeBackend(), q)
    r.load(_chunks(3))
    r.play()
    evs = _drain(q)
    assert [e for e in evs if e[0] == "chunk"] == [("chunk", 0), ("chunk", 1), ("chunk", 2)]
    assert evs[-1] == ("finished",)
    assert r.state == "idle"


def test_pause_resume_repeats_interrupted_sentence():
    q = queue.Queue()
    b = FakeBackend(per_chunk=0.3)
    r = Reader(b, q)
    r.load(_chunks(3))
    r.play()
    time.sleep(0.1)
    r.pause()
    time.sleep(0.15)
    assert r.state == "paused"
    assert b.spoken == ["s0"]
    r.play()
    evs = _drain(q, timeout=3)
    assert b.spoken == ["s0", "s0", "s1", "s2"]
    assert ("paused", 0) in evs and ("resumed", 0) in evs
    assert evs[-1] == ("finished",)


def test_jump_while_playing_and_stop():
    q = queue.Queue()
    b = FakeBackend(per_chunk=0.3)
    r = Reader(b, q)
    r.load(_chunks(5))
    r.play(0)
    time.sleep(0.1)
    r.play(3)  # jump
    time.sleep(0.15)
    assert b.spoken == ["s0", "s3"]
    r.stop()
    assert r.state == "idle"
    evs = _drain(q, timeout=1)
    assert evs[-1][0] == "stopped"
