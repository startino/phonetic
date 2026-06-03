# Wayland "global hotkeys unavailable" — trigger profiles by name + discoverability

**Date:** 2026-06-03
**Symptom:** After deploying v0.6.6/v0.6.7 on a NixOS Wayland host, the headless
service logs "Global hotkeys are unavailable here" and the operator's previously
working global hotkey no longer records. Operator: "it was working perfectly
well before on nixos, make it work for all profiles."
**Affected:** `phonetic/app.py:_resolve_profile` / `_toggle_recording`,
`phonetic/__main__.py` (`--trigger`, new `--list-profiles`), `README.md` Wayland section
**Root cause:** Two layers. (1) On Wayland no application can grab global
hotkeys — the compositor owns input. This was always true; the old setup
"worked" because the operator had a compositor key bound to the single legacy
`SIGUSR1` trigger (one global key → one profile). (2) v0.6.6 replaced `SIGUSR1`
with the per-profile `phonetic --trigger <id>` control FIFO — strictly more
capable (a signal can't carry *which* profile), but it (a) silently broke the
operator's old `kill -USR1` binding and (b) required binding opaque UUIDs, with
no way to discover them from the CLI.

## Investigation
1. v0.6.7 journal confirmed the service now runs (`active (running)`), so the
   earlier `Result: resources` was the pystray crash-loop aftermath (fix 0003),
   not this. The remaining complaint was purely the hotkey mechanism.
2. Confirmed `_is_wayland()` → `_SignalOnlyHotkeyManager`, so in-process global
   grabs are impossible by design; the compositor must `exec` the trigger.
3. The trigger CLI only accepted the profile `id` (a UUID for migrated
   profiles), making compositor bindings unreadable, and there was no
   `--list-profiles` to discover ids/names.

## Fix
- `app.py`: `_resolve_profile` now matches an exact `id` first, then a
  case-insensitive `name` — so `phonetic --trigger Work` works. `_toggle_recording`
  normalizes the incoming ref to the canonical id up front so the
  profile-switch comparison and `_recording_profile_id` stay id-based.
- `__main__.py`: `--trigger` documented as name-or-id; added `--list-profiles`
  (reads `profiles.json` directly — no audio detection — and prints name,
  hotkey, and the ready-to-bind `phonetic --trigger <ref>` command per profile).
- `README.md`: rewrote the Wayland section with the "compositor owns input"
  explanation, declarative NixOS Hyprland/Sway binding examples, and an explicit
  migration note from the old single `SIGUSR1` key.
- Tests: added name/case-insensitive resolution + id-precedence cases (50 pass).

Deliberately did NOT restore a `SIGUSR1`→first-profile bridge: it contradicts
the "no default profile" invariant and only ever triggered one profile, whereas
the operator asked for all profiles. The per-profile `--trigger` bindings are
the correct multi-profile answer.

**Commit:** see git log (v0.6.8)
