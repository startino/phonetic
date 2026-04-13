---
name: silence detection must not abort
description: Silence/audio detection must WARN only, never abort recording or skip transcription — false positives break working setups
type: feedback
---

Silence detection (peak < 0.001) must NEVER abort a recording or skip transcription. Only warn.

**Why:** The user's audio pipeline works correctly on NixOS/PipeWire/ALSA despite low float32 peak values. The abort behavior (introduced in ddede66 and e7351f7) repeatedly broke working recordings. This has been "fucked up and fixed" ~20 times because the same mistake keeps being made: adding an abort path to silence detection that kills recordings that would transcribe fine.

**How to apply:**
- Any audio silence check should only `print()` a warning and `_notify()` with urgency "normal" — never `return` early or call `stop()`
- The early audio check (1s after recording starts) must not stop the recording
- The final audio check (after stop) must not skip transcription
- Do NOT diagnose audio issues as "PortAudio lacks PulseAudio" — the ALSA/PipeWire device selection (commit 9e8655d) already fixed device routing. The recurring false diagnosis of "no PulseAudio backend" is a red herring.
