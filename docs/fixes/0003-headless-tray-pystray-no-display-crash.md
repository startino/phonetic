# Headless / systemd startup crash: tray (pystray) imported with no display

**Date:** 2026-06-03
**Symptom:** `phonetic.service` (the `--headless` systemd user service) crash-loops.
On a host with no X display reachable by the service, `python -m phonetic --headless`
exits 1 immediately at startup. (Operator also saw `Result: resources` / `Mem peak: 0B`
on the target host — that specific symptom is systemd-level and additionally addressed
by making the unit's EnvironmentFile optional; see Fix.)
**Affected:** `phonetic/app.py:20` (module-top `from .tray import TrayManager`),
`phonetic/tray.py:9-12` (import guard), `nix/module.nix` (EnvironmentFile)
**Root cause:** `app.py` imported `TrayManager` at module top, unconditionally — even in
headless mode. `tray.py` does `import pystray`, and pystray selects its backend **at import
time**; the X11 backend calls `Xlib.display.Display()` immediately, which raises
`Xlib.error.DisplayNameError: Bad display name ""` when there is no display. The guard only
caught `ImportError`, so the Xlib error escaped and crashed the process before `main()`'s
headless logic ran. Headless mode never uses the tray at all, so importing it was pure
collateral damage. Pre-existing (present at v0.6.5), surfaced by a service restart.

## Investigation
1. Reproduced locally: `XDG_CONFIG_HOME=tmp uv run python -m phonetic --headless` with no
   `DISPLAY`/`WAYLAND_DISPLAY` → traceback through `from .tray import TrayManager` →
   `import pystray` → `Xlib.error.DisplayNameError`.
2. `git show 4ff4497:phonetic/app.py` confirmed the top-level tray import predates the
   v0.6.6 work — a latent bug, not a v0.6.6 regression.
3. Noted the operator's host symptom was `Result: resources` + `Mem peak: 0B` (systemd
   never exec'd the binary) — a *different*, deploy-level failure class than this Python
   exit-code crash. Hardened the systemd unit defensively for the most likely such cause
   (a renamed/missing `EnvironmentFile` blocking exec).

## Fix
- `app.py`: removed the module-top `from .tray import TrayManager`; import it lazily inside
  `_start_services()` (GUI-only path). Headless never imports the tray now.
- `tray.py`: broadened the import guard from `except ImportError` to `except Exception`, so
  a display-less import degrades to `pystray = None` instead of crashing.
- `nix/module.nix`: `EnvironmentFile` is now prefixed with `-` (optional) so a missing env
  file can't fail the unit before exec — the app reads its key from `.env`/`config.env` in
  the config dir directly anyway.

Verified: `--headless` now starts past the import on a display-less box (only fails further
on genuinely-absent audio hardware, which is environmental). 48 tests pass.

**Commit:** see git log (v0.6.7)
