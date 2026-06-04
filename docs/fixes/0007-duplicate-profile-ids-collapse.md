# Duplicate profile ids collapse every keybind onto the first profile

**Date:** 2026-06-03
**Symptom:** With two profiles ("r" and "c") configured, every keybind — and
even `phonetic --trigger c` run manually — produced profile "r"'s output
(Victorian-English system prompt). All profiles behaved as the first one.
**Affected:** `phonetic/config.py:_load_profiles`
**Root cause:** The operator's `profiles.json` had **two profiles sharing the
same `id`** (`bb804489-...`, likely from duplicating a profile block without
changing the id). Every trigger path resolves a profile by id and returns the
FIRST match: a profile's own hotkey, the tray, and `--trigger <name>` (which
normalizes name→id in `_toggle_recording` before `_start_recording` re-resolves
by id). So `--trigger c` correctly found "c" by name, normalized to its id —
which equalled "r"'s id — then id-resolution returned "r". Duplicate ids are
corrupt state the app silently obeyed instead of defending against.

## Investigation
1. Read the operator's pasted `profiles.json`: both `profiles[].id` were the
   identical UUID. The two `system_prompt`s differed (only "r" had the
   "victorian english" instruction), matching the reported output.
2. Traced resolution: `_resolve_profile` matches id first, then name.
   `_toggle_recording` normalizes the incoming ref to `.id` up front (added in
   v0.6.8 for the profile-switch comparison) — so a name ref becomes the shared
   id, and the subsequent id lookup returns profile index 0.
3. Confirmed it's config corruption, not resolution logic: with distinct ids the
   same code resolves correctly.

## Fix
`_load_profiles` now enforces id uniqueness on load: any blank or duplicate id
is reassigned a fresh `uuid4`, a warning is logged to stderr (the journal), and
the healed list is persisted back to `profiles.json` so the fix is stable across
restarts and id-bindings stop aliasing. Triggering by **name** (recommended in
the Wayland docs) is unaffected and now resolves to the correct distinct
profile. Tests: duplicate-id heal (idempotent persist) + blank-id heal. 55 pass.

Immediate user workaround (pre-upgrade): give each profile a distinct `id` in
`profiles.json` (or just restart on v0.6.11, which auto-heals).

**Commit:** see git log (v0.6.11)
