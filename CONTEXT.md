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
- **areliant** (1.0.0+): a property of the Phonetic core — it imports, starts its daemon
  (via the extracted `start()` daemon-init path), and performs every configuration
  operation with all UI modules and GUI dependencies ABSENT from `sys.modules`
  (`None`-blocked, not merely uninstalled — blocking, not absence, is what the test
  asserts). The dependency arrow is strictly one-way: **UI → core, never core → UI**.
  Enforced by `tests/test_areliant.py`, which `None`-blocks the UI surface
  (`tkinter`/`tkinter.messagebox`, `customtkinter`, `pystray`, `PIL.*`,
  `phonetic.ui[.settings]`, `phonetic.tray`) while leaving the core deps
  (`sounddevice`, `soundfile`, `httpx`, `pynput`) resolvable, then drives import +
  config round-trip + real daemon-init. If the core ever imports the UI, it fails at
  import. The word is deliberate — the core is *areliant* (not *reliant*) on the UI
  (coined in ADR 0002). _Avoid_: "decoupled", "headless-capable" — those describe a
  runtime mode; *areliant* is an enforced structural invariant.
