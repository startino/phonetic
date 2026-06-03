# Headless service: "clipboard unavailable" — wl-copy can't reach the compositor

**Date:** 2026-06-03
**Symptom:** After the v0.6.7+ headless service finally completed a full
record→transcribe→copy cycle, transcription succeeded but the notification read
"Transcription ready (clipboard unavailable)". The operator had no clipboard
issues with earlier (in-session) phonetic usage.
**Affected:** `phonetic/clipboard.py` (`copy_to_clipboard`, new `_wayland_env`)
**Root cause:** Not a code regression — `clipboard.py` and
`platform_utils.py` were unchanged across the whole v0.6.x arc, and the nix
package already wraps `wl-clipboard`/`xclip` onto PATH (so `wl-copy` is found).
The real cause: the **headless systemd user service does not inherit
`WAYLAND_DISPLAY`** from the compositor session (systemd only exports it if the
compositor runs `systemctl --user import-environment WAYLAND_DISPLAY`). With it
unset, `wl-copy` falls back to `wayland-0` and fails to connect when the
compositor uses `wayland-1` (common on Hyprland) — raising `CalledProcessError`,
caught as "clipboard unavailable". It "worked before" because the operator ran
phonetic *inside* the graphical session, where `WAYLAND_DISPLAY` was set; the
crash-looping service never reached the clipboard step until v0.6.7 fixed
startup, so this surfaced only now.

## Investigation
1. Grepped `docs/fixes/` (only the unrelated 0001 429 fix mentioned clipboard).
2. `git log -- phonetic/clipboard.py phonetic/platform_utils.py`: last change was
   the original refactor `118be50` — my v0.6.7–v0.6.9 updates touched neither.
   Ruled out a code regression.
3. `nix/package.nix`: `makeWrapperArgs --prefix PATH` includes `wl-clipboard`
   and `xclip`, and the service runs the wrapped binary (`.phonetic-wrapped`).
   So `wl-copy` is on PATH — not a FileNotFoundError. The failure is a non-zero
   exit = a Wayland *connect* failure, i.e. missing/wrong `WAYLAND_DISPLAY`.
4. The earlier headless `Session: wayland` log proves `_is_wayland()` is true via
   the socket-existence check, even though `WAYLAND_DISPLAY` is not exported —
   exactly the condition where wl-copy's `wayland-0` default can miss.

## Fix
`clipboard.py`: added `_wayland_env()` — when `WAYLAND_DISPLAY` is unset, fill
`XDG_RUNTIME_DIR` (default `/run/user/$UID`) and discover the live socket
(`wayland-0/1/2`), setting `WAYLAND_DISPLAY` in the env passed to `wl-copy`, so
it connects regardless of what the service inherited. Also added a `shutil.which`
precheck (clear "not on PATH" message) and a `CalledProcessError` handler that
reports the exit code + the `WAYLAND_DISPLAY` used (the tool's own stderr already
goes to the journal). Deliberately kept the no-output-capture behavior:
wl-copy/xclip fork a daemon that holds inherited fds, so piping their output
would block until the timeout. Tests: `tests/test_clipboard.py` covers
passthrough / discovery / no-socket. 53 tests pass.

**Commit:** see git log (v0.6.10)
