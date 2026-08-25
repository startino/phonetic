"""Regression tests for the early-silence warning (ADR 0003).

The bug: the silence warning surfaced only at stop-time, never during the
recording, because the one forward check was a single +1s shot over a *latching*
whole-buffer peek. The fix is a pure continuous-silence state machine
(`phonetic.silence.SilenceMonitor`) fed a *windowed* peak from a new
`Recorder.peek_window_level()`.

Both halves are hardware-free:
* Part A drives `SilenceMonitor` with fabricated peak levels — no Recorder, no
  sounddevice, no GUI. It pins the semantics the ADR mandates: continuous (not
  cumulative), strict `<` threshold, single-warning latch, reset.
* Part B drives `Recorder.peek_window_level()` by stuffing synthetic np.ndarray
  frames onto `rec._q` (a plain queue.Queue) — the same pattern
  `test_transcribe_long_recording.py` uses for synthetic audio. `sounddevice` is
  stubbed exactly as `test_app_profiles_wave2.py` does so `phonetic.recorder`
  imports without PortAudio.
"""
import sys
import types

# Stub sounddevice so `phonetic.recorder` imports without the native lib (mirrors
# tests/test_app_profiles_wave2.py:23-24).
if "sounddevice" not in sys.modules:
    sys.modules["sounddevice"] = types.ModuleType("sounddevice")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from phonetic.constants import SILENCE_PEAK_THRESHOLD, SILENCE_WARN_SECS  # noqa: E402
from phonetic.recorder import Recorder  # noqa: E402
from phonetic.silence import SilenceMonitor  # noqa: E402


# --- Part A: SilenceMonitor (synthetic levels, no Recorder) ------------------


def test_fires_once_after_5s_continuous_silence():
    """5 unbroken silent windows at 1s each cross warn_secs=5.0 -> exactly one
    True, on the 5th feed (1+1+1+1+1 == 5.0, `>=` fires). False before and after."""
    m = SilenceMonitor(warn_secs=5.0)
    results = [m.feed(0.0, 1.0) for _ in range(6)]
    assert results == [False, False, False, False, True, False]
    assert sum(results) == 1


def test_no_fire_when_audio_present():
    """A level >= threshold every window never accrues silence -> never warns."""
    m = SilenceMonitor(warn_secs=5.0)
    results = [m.feed(0.2, 1.0) for _ in range(10)]
    assert results == [False] * 10


def test_reset_on_loud_window():
    """CONTINUOUS, not cumulative (ADR 0003 / Linus Q1): a single loud window in
    the middle RESETS the accumulator, so 5s of *unbroken* silence is never
    reached. Cumulative would have warned here — this test forbids cumulative."""
    m = SilenceMonitor(warn_secs=5.0)
    levels = [0.0, 0.0, 0.0, 0.2, 0.0, 0.0]
    results = [m.feed(lvl, 1.0) for lvl in levels]
    assert results == [False] * len(levels)


def test_boundary_at_threshold_is_strict_less_than():
    """Strict `<` parity with the legacy `peak < 0.001`: a level EXACTLY equal to
    the threshold counts as NOT silent (resets); a level just below it for 5s
    DOES warn."""
    # Exactly at threshold -> never silent -> never warns.
    at = SilenceMonitor(warn_secs=5.0)
    assert [at.feed(SILENCE_PEAK_THRESHOLD, 1.0) for _ in range(6)] == [False] * 6

    # Just below threshold for 5s -> warns once on the 5th feed.
    below = SilenceMonitor(warn_secs=5.0)
    lvl = SILENCE_PEAK_THRESHOLD - 1e-9
    res = [below.feed(lvl, 1.0) for _ in range(6)]
    assert res == [False, False, False, False, True, False]


def test_single_warning_latch():
    """Once fired, further silence yields no second warning until reset(); after
    reset, a fresh 5s of silence fires True again exactly once."""
    m = SilenceMonitor(warn_secs=5.0)
    first = [m.feed(0.0, 1.0) for _ in range(8)]
    assert sum(first) == 1
    assert first[4] is True  # fired on the 5th feed, latched thereafter
    m.reset()
    second = [m.feed(0.0, 1.0) for _ in range(6)]
    assert second == [False, False, False, False, True, False]


def test_reset_clears_accumulator_not_just_latch():
    """reset() zeroes the silence counter, not only the latch: 3 silent windows,
    reset, then 4 more must NOT warn yet (counter restarted) — the 5th does."""
    m = SilenceMonitor(warn_secs=5.0)
    assert [m.feed(0.0, 1.0) for _ in range(3)] == [False, False, False]
    m.reset()
    assert [m.feed(0.0, 1.0) for _ in range(4)] == [False, False, False, False]
    assert m.feed(0.0, 1.0) is True  # only now (5 since reset) does it warn


def test_default_warn_secs_matches_constant():
    """The user's explicit '5 seconds' lives in constants, not a magic literal."""
    assert SilenceMonitor().warn_secs == SILENCE_WARN_SECS


# --- Part B: Recorder.peek_window_level (synthetic frames on rec._q) ----------


def _make_recorder():
    """A Recorder with no device, marked recording, ready to receive synthetic
    frames on its queue. `peek_window_level` early-returns on is_recording False,
    so we flip it by hand (we never call start(), which needs PortAudio)."""
    rec = Recorder(sample_rate=16000, channels=1)
    rec.is_recording = True
    return rec


def test_window_level_returns_max_of_new_frames_only():
    """Windowed, not latching: the first call returns the max over the frames
    drained that call; a subsequent quieter window returns ITS max, not the
    earlier latched loud value."""
    rec = _make_recorder()
    rec._q.put(np.array([0.0, 0.0], dtype=np.float32))
    rec._q.put(np.array([0.0, 0.5], dtype=np.float32))
    assert rec.peek_window_level() == 0.5  # max over the two new frames

    rec._q.put(np.array([0.1], dtype=np.float32))
    # ONLY the new window — the latched 0.5 from before is gone (anti-latch).
    assert rec.peek_window_level() == pytest.approx(0.1)


def test_window_level_zero_when_no_new_frames():
    """No frames since the last call -> 0.0, a genuine silent-window signal."""
    rec = _make_recorder()
    rec._q.put(np.array([0.3], dtype=np.float32))
    assert rec.peek_window_level() == pytest.approx(0.3)
    # Queue now empty; nothing new arrived.
    assert rec.peek_window_level() == 0.0


def test_window_level_not_recording_returns_zero():
    """Not recording -> 0.0 regardless of queued frames (early-return guard)."""
    rec = _make_recorder()
    rec._q.put(np.array([0.9], dtype=np.float32))
    rec.is_recording = False
    assert rec.peek_window_level() == 0.0


def test_window_read_preserves_frames_for_stop():
    """The windowed read drains _q into _frames (never drops), so the final
    stop() still sees every sample (R5). The cursor tracks the measured window."""
    rec = _make_recorder()
    rec._q.put(np.array([0.0, 0.2], dtype=np.float32))
    rec._q.put(np.array([0.0, 0.0], dtype=np.float32))
    rec.peek_window_level()
    assert len(rec._frames) == 2          # frames retained for stop()
    assert rec._peeked_frames == 2        # window cursor advanced to the end
