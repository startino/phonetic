# Silence warning only fired at stop, not during recording

**Date:** 2026-06-05
**Symptom:** A user recorded a 10-minute silent voice message; the "audio may be
silent" warning appeared only AFTER stopping the recording — too late to act, the
take was already lost. The user expected the warning within ~5 seconds of silence.
**Affected:** `phonetic/app.py` (`_start_recording`, the deleted `_check_early_audio`
-> new `_schedule_silence_tick`/`_silence_tick`, `_stop_recording_and_transcribe`),
`phonetic/recorder.py` (`peek_window_level`), `phonetic/constants.py`
(`SILENCE_*`), new `phonetic/silence.py` (`SilenceMonitor`).
**Root cause:** There was no continuous silence monitor. The only forward-looking
check was a single +1s one-shot (`_check_early_audio`) over `peek_level`, a
monotonic whole-buffer peak that LATCHES high once any frame is loud — so one
early non-silent frame hid silence for the rest of the take, and nothing
re-checked. The dependable signal was the post-stop whole-buffer peak, which by
construction only fires after the user stops. The early warning was also
`replace=True` at `"low"` urgency, so even when it fired it replaced the
"Recording started" bubble and went unnoticed (diagnosis 3b).

## Investigation
1. Traced the two warn sites in `phonetic/app.py`: Site A, the one-shot
   `_check_early_audio` scheduled once at +1s (`app.py:461-465`, `app.py:516-529`);
   Site B, the post-stop whole-buffer peak (`app.py:484-495`). Confirmed Site B is
   the only one the user reliably sees, and it can only fire after stop.
2. Read `peek_level` (`recorder.py:60-79`): it is `max|abs|` over ALL frames since
   `start()` -> monotonic non-decreasing across calls. Any early noise (a breath,
   a click, half a second of speech) permanently masks later silence. A naive
   *repeated* `peek_level` would also latch — so the monitor needed a WINDOWED read
   that measures only the frames drained since the last call.
3. Dead end considered: **cumulative** silence counting (sum all sub-threshold
   time). Rejected — it false-fires on normal speech, where every pause and breath
   accrues, so a perfectly good long recording would warn mid-sentence.
   **Continuous** (a loud window resets the accumulator) is correct.
4. Dead end considered: **aborting/discarding** on detected silence. Rejected —
   PipeWire/ALSA legitimately deliver sub-0.001 float32 peaks that still transcribe
   (standing comment at `app.py:484-486`); aborting on a misread would destroy a
   real take. The user already lost 10 minutes once. Warn-only, recording always
   continues.
5. Stale-tick hazard: `is_recording` alone cannot disambiguate a tick from a prior
   recording, because the profile-switch path (`app.py:408-420`) stops one take and
   starts another in the same thread with `is_recording` staying True. Resolved
   with a per-recording monotonic generation token captured at schedule time; a
   tick whose token != current is a no-op.

## Fix
Added a pure `SilenceMonitor` state machine (`phonetic/silence.py`): continuous 5s
gate, single-warning latch, `reset()`; imports only stdlib + `.constants`. Added
`Recorder.peek_window_level()` (peak of only the frames drained this call; returns
0.0 on no new frames; frames preserved for the final `stop()` via a frame-count
cursor). Promoted the magic `0.001` plus the 5s/1s timings into
`SILENCE_PEAK_THRESHOLD`/`SILENCE_WARN_SECS`/`SILENCE_POLL_SECS` in `constants.py`,
and switched the post-stop backstop to the constant (strict `<` preserved).
Replaced the +1s one-shot with a repeating, generation-token-tagged monitor
(`_schedule_silence_tick`/`_silence_tick`: GUI `self._root.after`, headless
`threading.Timer` chain); deleted `_check_early_audio`. The live warning is now a
fresh `"normal"` notification (no `replace`). The generation bumps in both
`_start_recording` (new take) and `_stop_recording_and_transcribe` (kills old
ticks), covering the profile-switch path; `_start_recording` also constructs a
FRESH `SilenceMonitor()` per recording, so each take starts from clean state
(the `reset()` method is a pure-class API used by the tests, not the
per-recording mechanism in `app.py`). ADR 0003 records the invariant. All
existing `log()`/`print` lines retained; the monitor adds per-tick level logging
and a log when the warning fires.

**Commit:** see `feat(audio): continuous silence monitor warns during recording`
on `worktree-fix+early-silence-warning` (this file ships in that same commit).
