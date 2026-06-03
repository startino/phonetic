# Phonetic — Domain Context

Glossary of the project's domain language. Keep terms here stable; code and ADRs
reference them.

## Terms

- **Transcription pipeline**: the path from recorded audio to final clipboard text.
  Historically a single multimodal-LLM call (transcribe + format in one). Moving to a
  two-stage pipeline (see ADR 0001).
- **ASR (stage A)**: speech-to-text. Audio in, raw transcript out. Pluggable backend —
  a dedicated ASR model (e.g. `nvidia/parakeet-tdt-0.6b-v3`) or a multimodal LLM acting
  as ASR. NOT promptable when the backend is a pure ASR model.
- **Format/rewrite (stage B)**: takes a raw transcript plus a prompt and produces the
  final text (clean-up, formatting, tone rewrite). Always a text LLM. This is the
  "promptable" half of Phonetic.
- **Promptability**: Phonetic's ability to shape output via a user prompt — formatting
  rules, filler removal, full tone rewrite. Lives in stage B, not in the ASR model.
- **Profile**: a named binding of `{ hotkey, model, asr-model, format-model, prompt }`.
  Every profile carries its own model and hotkey; there is **no default profile** and no
  global model/hotkey. Recording is only ever triggered by a profile's own hotkey, a tray
  selection, or `phonetic --trigger <id>`. Multiple profiles let one hotkey mean "email
  tone", another "texting", another "prompt-for-an-LLM", etc.
- **Model field**: the OpenRouter model id, configured per-profile (each profile's
  `model` is its single-call / fallback-format model; `asr_model` + `format_model` drive
  the two-stage path). There is no global model field.
- **Config split (0.6.6+)**: three files in the config dir — `.env` (secret only),
  `settings.json` (toggles: notify/verbose/auto_start/device), `profiles.json` (profiles).
  A pre-0.6.6 `config.env` is auto-migrated on first launch.
