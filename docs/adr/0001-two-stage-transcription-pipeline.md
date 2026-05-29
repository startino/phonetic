# ADR 0001: Split transcription into a two-stage pipeline (ASR + format)

- Status: Accepted
- Date: 2026-05-29

## Context
Phonetic transcribes audio by making one multimodal `chat/completions` call to
OpenRouter (`phonetic/transcribe.py`): the system prompt and the base64 WAV go in the
same request, and a single multimodal LLM (default `google/gemini-3-flash-preview`)
both transcribes and applies the user's formatting/tone prompt. The "promptability"
users value is a property of this multimodal call.

Two pressures break this design:
1. Google does not allow Hong Kong companies to use Gemini, so the org lost its default
   model.
2. The cheap, fast, multilingual model the user wants (`nvidia/parakeet-tdt-0.6b-v3`,
   $0.0015/min) is a PURE ASR model — verified not promptable and not served via
   `chat/completions` `input_audio`. It returns transcribed text only.

A pure ASR model cannot, by itself, format or rewrite output. Keeping promptability
while gaining access to dedicated ASR models requires separating the two concerns.

## Decision
Split transcription into two explicit stages:
- **Stage A (ASR)**: audio -> raw transcript. Backend is pluggable: a dedicated ASR
  endpoint (Parakeet) or a multimodal LLM used as ASR.
- **Stage B (format/rewrite)**: raw transcript + prompt -> final text, via a text LLM.

Configuration grows an ASR-model field and a format-model field alongside the existing
prompt. The default configuration reproduces today's behaviour (one capable model can
serve both stages), so existing users are unaffected.

This split is also the foundation for per-keybind profiles (see ADR 0002 when written):
decoupling the prompt from transcription is what lets each hotkey carry its own
prompt + model.

## Consequences
- Two API calls (or one, when a single model serves both) instead of always one — more
  latency in the two-call path, offset by far cheaper/faster ASR and full model choice.
- Promptability is preserved and now independent of the ASR backend.
- HK org is unblocked at the architecture level (stage B can be any non-geo-blocked
  text LLM; stage A can be Parakeet).
- The immediate Gemini block is handled separately as an urgent default-model swap and
  does not wait for this refactor.
