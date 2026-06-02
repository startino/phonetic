# Long recordings silently fail (oversized payload → upstream 429 → empty output)

**Date:** 2026-06-02
**Symptom:** A single ~3.5-minute recording deterministically produced a
low-urgency "Empty transcription" notification with nothing on the clipboard.
Short recordings worked fine. No error was shown to the user; the audio was lost.
**Affected:** `phonetic/transcribe.py` (all four send paths); surfaced via
`phonetic/app.py:515` (`_transcribe_worker`) → `app.py:533-535` (empty branch).
**Root cause:** Two independent defects combined.

- **Bug A — payload size dead-zone.** At 44.1 kHz a 3.5-min recording is an
  18.2 MB WAV / 24.3 MB base64 body, which the upstream provider (Mistral via
  OpenRouter) rejects. The downsample guard only fired when WAV bytes exceeded
  `_MAX_WAV_BYTES = 20_000_000` — a threshold that sat *above* the size that
  already fails, and measured raw WAV bytes rather than the ~1.33x-larger
  base64 body actually transmitted. So 18.2 MB < 20 MB → guard skipped →
  44.1 kHz audio sent unmodified → rejected.
- **Bug B — silent failure.** OpenRouter wraps upstream provider errors in an
  **HTTP 200** body (`{"error":{"message":"Provider returned error","code":429}}`,
  no `choices`). The response handler only branched on non-2xx
  (`if not resp.is_success`), so the error object was never inspected:
  `data.get("choices")` → `None` → `[{}]` → `""`. A hard provider rejection was
  laundered into a benign empty result.

## Investigation
1. Reporter supplied a definitive reproduction: same 206.6 s / 44.1 kHz clip
   submitted 4x. Three sends at 44.1 kHz (24.3 MB base64) → HTTP 200 with the
   429 error body → 0 chars. One send at 16 kHz (8.8 MB base64) → normal
   `choices`, 2807 chars. Retries minutes apart returned the *identical* 429 →
   not frequency rate-limiting; the only variable that mattered was payload size.
2. Confirmed the diagnosis against the code verbatim: `_MAX_WAV_BYTES` at L16,
   the dead-zone guard at L100-101, the success-only check at L154-160, and the
   empty extraction at L165.
3. Found the same two defects duplicated in the two-stage path the report did
   NOT trace: `_prepare_audio` (downsample guard), `_run_asr` chat-style and
   ASR-only sites, and `_run_format` (200-with-error → silent `""`). A
   single-source-of-truth fix had to cover all four call sites, not just legacy.

## Fix
- **Bug A:** removed the `_MAX_WAV_BYTES` threshold entirely. New
  `_to_send_audio()` *always* renders the send payload at ≤16 kHz mono (Voxtral
  and the other OpenRouter ASR models are 16 kHz-native; native-rate capture
  buys ASR nothing and inflates the payload ~2.75x). No byte threshold to get
  wrong → the dead zone cannot exist. The full-quality debug WAV is still
  written before downsampling, via the extracted `_save_debug_wav()`.
- **Bug B:** new `_parse_response()` raises on a non-2xx status OR a 200 body
  carrying an `{"error":...}` object; `_chat_text()` raises on a 200 response
  with no `choices`. Both raise `RuntimeError("OpenRouter <code>: <message>")`,
  which propagates to `_transcribe_worker` → the `transcription_error` →
  **critical** notification path. A 200-with-error body can never again become
  "Empty transcription." Applied at all four send sites.
- Regression tests in `tests/test_transcribe_long_recording.py` cover the
  unconditional downsample (incl. stereo→mono and the 16 kHz pass-through) and
  the 200-with-error / no-choices raise across legacy, two-stage chat ASR,
  ASR-only, and the format stage.

**Commit:** see PR to `alpha`.
