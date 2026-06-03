# Dead per-profile keys written to config.env

**Date:** 2026-06-03
**Symptom:** Operator inspecting `~/.config/phonetic/config.env` (and the
auto-generated `config.env.example`) saw `ASR_MODEL`, `FORMAT_MODEL`, and
`SYSTEM_PROMPT` documented as if they were live top-level settings. Editing
them there had no effect on transcription once `profiles.json` existed —
misleading, looks-live-but-dead config.
**Affected:** `phonetic/config.py` (`_format_config_env`, `_format_example_config_env`,
`Config._SAVE_FIELDS`/`_FIELD_ENV_MAP`), `.env.example`, `tests/test_config_wave1.py`
**Root cause:** Wave 2 moved per-hotkey transcription (ASR model, format model,
system prompt) into `profiles.json`. The transcribe path reads them
exclusively from the active profile (`app.py:507-511`:
`profile.asr_model` / `.format_model` / `profile.system_prompt or cfg.system_prompt`).
The top-level `Config.asr_model` / `.format_model` are **never consulted at
transcribe time**. But the config.env writer and example generator were never
updated — they kept emitting those three keys, so a saved `config.env`
contradicted reality and the example taught users a dead knob.

## Investigation
1. Traced `cfg.asr_model` / `cfg.format_model` / `cfg.system_prompt` usage in
   `transcribe.py` — they ARE read there, but on the `cfg` object that
   `_transcribe_worker` rebuilds via `dataclasses.replace(self._cfg,
   asr_model=profile.asr_model, ...)`. So the *profile* values overwrite the
   top-level ones before transcription. The top-level fields are write-only.
2. Confirmed `system_prompt` is the one partial survivor: `profile.system_prompt
   or self._cfg.system_prompt` — the top-level acts as a blank-profile fallback
   only. `asr_model`/`format_model` have no fallback to cfg at all.
3. Confirmed `load_config()` still READS legacy `ASR_MODEL`/`FORMAT_MODEL`/
   `SYSTEM_PROMPT` env keys (seeds the synthesized default profile on first
   run) — so removing them from the *writer* is safe and back-compat is kept;
   we just stop writing a misleading mirror.
4. `_SAVE_FIELDS` / `_FIELD_ENV_MAP` class vars: grepped — zero references
   anywhere. Dead. Removed.

## Fix
- `_format_config_env` and `_format_example_config_env` now emit only the keys
  config.env owns: `OPENROUTER_API_KEY`, `MODEL`, `HOTKEY`, `NOTIFY`,
  `AUTO_START`, with a "what lives where" header routing per-hotkey settings to
  `profiles.json`.
- Kept `load_config()` honoring the legacy keys for back-compat (seeds default
  profile); only the write path changed.
- Removed unused `Config._SAVE_FIELDS` / `_FIELD_ENV_MAP`.
- `.env.example`: same split; legacy keys demoted to clearly-labelled
  commented-out seed-only examples.
- Tests: round-trip now asserts per-hotkey settings persist via `profiles.json`;
  serialization test renamed to assert config.env OMITS the per-profile keys.

**Commit:** `3954e34`
