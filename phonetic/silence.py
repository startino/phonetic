"""Pure continuous-silence detector for the live recording monitor.

This module is the UNIT-TESTABLE SEAM for the early-silence warning (ADR 0003).
It is dependency-light by design: it imports ONLY stdlib + `.constants`. It has
NO knowledge of sounddevice, numpy, tkinter, the Recorder, `_root`, threading, or
I/O. It consumes a single windowed peak `level` per tick (a float the caller has
already measured) plus the elapsed `dt` for that window, and answers exactly one
question: "should the caller emit a warning right now?"

Keeping the silence logic pure here is what lets the regression tests in
`tests/test_silence_monitor.py` exercise every edge (continuous-reset, strict
threshold boundary, single-warning latch, reset) with fabricated levels and zero
hardware. The threading wrapper in `phonetic/app.py` stays thin: schedule, read
the windowed level, `feed`, act on the boolean.
"""
from .constants import SILENCE_PEAK_THRESHOLD, SILENCE_WARN_SECS


class SilenceMonitor:
    """Pure continuous-silence detector.

    Fed one windowed peak `level` per tick along with the elapsed `dt` seconds
    for that window. Tracks how long audio has been CONTINUOUSLY below
    `threshold`: any window with `level >= threshold` RESETS the accumulator.
    Fires EXACTLY ONCE when continuous sub-threshold time reaches `warn_secs`,
    then latches until `reset()`. Never aborts anything — the caller decides
    only whether to emit a (single) warning.
    """

    def __init__(
        self,
        threshold: float = SILENCE_PEAK_THRESHOLD,
        warn_secs: float = SILENCE_WARN_SECS,
    ) -> None:
        self.threshold = threshold
        self.warn_secs = warn_secs
        self._silent_secs = 0.0
        self._warned = False

    def reset(self) -> None:
        """Clear all state for a fresh recording (called on record-start)."""
        self._silent_secs = 0.0
        self._warned = False

    def feed(self, level: float, dt: float) -> bool:
        """Advance the machine by one window.

        Returns True EXACTLY on the tick that first crosses warn_secs of
        continuous silence (the caller should emit one warning); False every
        other tick, including all subsequent silent ticks after it has fired
        (single-warning latch) and any tick with audio present.
        """
        if level < self.threshold:           # STRICT < — matches app.py legacy
            self._silent_secs += dt
        else:
            self._silent_secs = 0.0          # CONTINUOUS: loud window resets
            return False
        if self._warned:                     # already fired this recording
            return False
        if self._silent_secs >= self.warn_secs:
            self._warned = True
            return True
        return False
