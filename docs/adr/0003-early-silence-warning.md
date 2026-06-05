# ADR 0003: Warn during recording when audio is silent

- Status: Accepted
- Date: 2026-06-05
- Affects: `phonetic/app.py` record-start path, `phonetic/recorder.py`,
  `phonetic/notifications.py`, `phonetic/constants.py`; new `phonetic/silence.py`.
  ADR 0001 (two-stage pipeline) and ADR 0002 (CLI-first core) are unaffected.

## Context

Phonetic had two places that warned about silent audio, and the dependable one
fired too late to help the user.

- **The forward-looking check was a single one-shot at +1s.** `_start_recording`
  scheduled `_check_early_audio` exactly once (`self._root.after(1000, ...)` in
  GUI mode, a one-shot `threading.Timer` headless) and never rescheduled it. That
  check read `Recorder.peek_level()`, which is `np.max(np.abs(...))` over **every
  frame captured since `start()`** — a monotonic, whole-buffer peak that **latches
  high** the moment any single frame is non-silent. So one early breath, click, or
  half-second of speech made the +1s check pass, and *nothing re-checked* for the
  rest of the take. A mic that died mid-recording was invisible.
- **The dependable signal was the post-stop peak.** The only reliable silence
  warning was the whole-buffer peak computed in `_stop_recording_and_transcribe`,
  which by construction can only fire **after the user ends the recording**.
- **Concrete user harm:** a 10-minute silent voice message produced no warning
  until stop. The take was already lost. The warning was backwards in time — the
  exact complaint that opened this fix.
- **The early warning was also invisible even when it fired.** It used
  `replace=True` at `"low"` urgency, replacing the persisted "Recording started"
  bubble (`notifications.py` reuses `_notify_id` on `replace`). The post-stop
  warning posted a *fresh* notification, so that was the one the user consciously
  registered — reinforcing "the warning only comes at stop."

## Decision

**INVARIANT:** A silence warning MUST surface DURING recording, at the earliest
reliably-distinguishable point (target: 5 seconds of CONTINUOUS sub-threshold
audio), and MUST NEVER be deferred to stop-time as the primary signal.

The implementation pins the following, each with its justification:

- **Continuous, not cumulative.** A single window with `level >= threshold` RESETS
  the silence accumulator; only 5s of *unbroken* sub-threshold audio fires. WHY:
  cumulative counting would accrue every normal speech pause and breath, and
  false-fire mid-sentence on a long, perfectly-good recording — the very
  false-positive class this fix must avoid. (Pinned by
  `tests/test_silence_monitor.py::test_reset_on_loud_window`.)

- **Threshold `SILENCE_PEAK_THRESHOLD = 0.001`** (~ -60 dBFS on the float32
  [-1, 1] scale), compared with strict `<` so the boundary value is NOT silent —
  identical to the pre-existing `peak < 0.001`. A WINDOWED level plus a DURATION
  gate (5s continuous) is safer than any single sample: a transient quiet window
  cannot trip it, and the threshold lives once in `constants.py` (single source of
  truth), imported by both the live monitor and the post-stop backstop.

- **Warn, never abort.** The monitor only emits a notification; the recording
  always continues. WHY: PipeWire/ALSA legitimately deliver sub-0.001 float32
  peaks that still transcribe fine (the standing comment at `app.py:484-486`). A
  false positive must NEVER discard or stop a take — the user already lost 10
  minutes once; aborting on a misread would be catastrophic where warning is
  cheap.

- **Noticeable.** A fresh notification at urgency `"normal"` — not `"low"` +
  `replace` (the original invisibility bug), and not `"critical"` (too alarming
  for a non-fatal warn-and-continue). The user consciously registers it without
  being alarmed.

- **Per-recording generation token.** Every scheduled tick carries a monotonic
  generation id captured at schedule time; a tick whose id no longer matches the
  current recording is a no-op. WHY: `is_recording` alone is insufficient — the
  profile-switch path (`app.py:408-420`) stops one recording and starts another in
  the same thread, keeping `is_recording` True across two distinct takes. The
  token is what stops a stale tick from recording N bleeding a warning into
  recording N+1. The pure state machine is reset per recording in
  `_start_recording`.

- **Post-stop check demoted to a backstop.** The whole-buffer peak warning at
  `app.py:484-495` is KEPT — it still catches a take shorter than the 5s gate the
  live monitor can never reach — but it is no longer the primary signal, and its
  `0.001` literal now reads from `SILENCE_PEAK_THRESHOLD`.

- **Pure state machine in its own module.** `phonetic/silence.py` holds
  `SilenceMonitor`, which imports only stdlib + `.constants` (no sounddevice,
  numpy, tkinter, Recorder, `_root`, or I/O). It consumes a windowed level and a
  timestep and answers "warn now?". This is the unit-testable seam; the threading
  wrapper in `app.py` (GUI `after` / headless `Timer` chain) stays thin.

## Consequences

- **Positive:** silence is surfaced ~5s into the recording instead of at stop;
  mid-recording device loss is now detectable because the monitor reads a moving
  *windowed* level (`Recorder.peek_window_level()`), not the latching whole-buffer
  peek; the warning is finally visible (fresh `"normal"` notification, no replace);
  and the silence logic is a pure state machine, fully unit-testable with
  synthetic levels — no microphone, no GUI, no audio device.
- **Negative / accepted:** a 1s poll adds a small periodic cost while recording —
  one windowed max over a ~1s frame slice, which is bounded (unlike re-scanning
  the whole buffer every tick, which `peek_level` would have done). A
  legitimately-quiet-but-real source could draw a single warning, but the take is
  always preserved (warn-don't-abort) — an accepted trade against ever losing
  audio again.
