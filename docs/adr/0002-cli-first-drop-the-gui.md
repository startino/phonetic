# ADR 0002: v0.7 — go CLI-first and drop the desktop GUI

- Status: Proposed
- Date: 2026-06-04
- Supersedes parts of: the tray + settings-window UX (ADR 0001 is unaffected;
  the two-stage pipeline stays)

## Context

Phonetic has two faces:

1. **A config-driven daemon.** `phonetic --headless` runs with no display, reads
   three JSON/`.env` files (`config.py`), registers per-profile hotkeys, and is
   triggered either by a profile's own hotkey or by `phonetic --trigger <name>`
   (the Wayland/compositor path). This face is small, testable, and already the
   default on Linux.

2. **A desktop GUI.** A `pystray` tray icon (`tray.py`, 254 lines) plus a
   `customtkinter` settings window that doubles as the first-run wizard
   (`ui/settings.py`, 615 lines), driven by a tkinter mainloop in `app.py`.

The GUI is where nearly all the platform pain lives. The macOS notes in
`CLAUDE.md` are almost entirely GUI-coupling workarounds: `LSUIElement` blocking
permission dialogs, `tkinter` having to init **before** AppKit or Tk crashes,
PyObjC block-signature registration, `pynput`'s `CGEventTap` needing Input
Monitoring, `pynput` listeners crashing on Sequoia from a background thread,
Option-key character composition, AppTranslocation, and the
`com.apple.provenance` dylib block. The dependency surface the GUI pulls in
(`pystray`, `customtkinter`, `Pillow`, `pyobjc-framework-Cocoa`,
`pyobjc-framework-ApplicationServices`) is the largest and most fragile part of
the build, and the bundling (`packaging/phonetic.spec`, the whole macOS
install-testing chapter in `CLAUDE.md`) exists mostly to ship it.

Meanwhile the daemon face has matured to where it can stand alone: there is no
default profile, no global model/hotkey, config is three purpose-scoped files,
and triggers resolve by readable profile **name** (ADR-adjacent work through
v0.6.12). Editing a JSON file and binding a shortcut is the whole interaction.

**The key constraint that shapes this ADR:** dropping the GUI is *not* the same
as dropping the macOS `.app` bundle. macOS microphone permission (TCC) attaches
to an application's **own** bundle identity (`no.starti.phonetic`) and the grant
dialog only appears when the app is a **foreground** app. `_check_mic_permission`
(`app.py:631`) already does this with AppKit directly — `NSApplication`
`setActivationPolicy_(Regular)` + `activateIgnoringOtherApps_` + AVFoundation —
and that code needs **AppKit, not customtkinter**. A bare CLI binary launched
from a terminal would request permission under the *terminal's* TCC identity, not
Phonetic's, and could not show its own dialog. So on macOS the app must remain a
bundled `.app` with an AppKit moment for the one-time mic grant; it does not need
a tray or a settings window.

## Decision (proposed)

Make the config-driven daemon the product on every platform and remove the
desktop GUI. Concretely:

### Remove
- `phonetic/tray.py` (pystray tray icon + menu).
- `phonetic/ui/settings.py` (customtkinter settings window / first-run wizard).
- The tkinter mainloop and GUI message-pump branch in `app.py`.
- Dependencies: `pystray`, `customtkinter`, `Pillow`, and the customtkinter-only
  use of tkinter. (PyObjC stays on macOS — see below.)

### Keep
- The headless daemon, the three-file config model, `--trigger <name>`,
  `--list-profiles`, per-profile hotkeys, the two-stage pipeline (ADR 0001), and
  all logging.
- On macOS: the **`.app` bundle** and the **AppKit mic-permission shim**
  (`_check_mic_permission`) — minus tkinter coupling. Carbon
  `RegisterEventHotKey` (`quickmachotkey`, `hotkeys.py`) already needs no
  permissions and is GUI-independent.

### Add (the CLI surface that replaces the settings window)
- `phonetic config` — a small TTY editor / printer for the three config files
  (`phonetic config list`, `phonetic config add-profile`,
  `phonetic config edit <name>`, `phonetic config path`). This is the
  replacement for the settings GUI; it manipulates the same JSON the GUI did.
- `phonetic grant-mic` (macOS) — briefly becomes a foreground app and triggers
  the AVFoundation TCC dialog, then exits. The documented one-time first-run step.
- `phonetic doctor` — prints permission/hotkey/clipboard/daemon status (it already
  has most of these checks internally; surface them).

### Per-platform end state
- **Linux:** already here. Document the headless service + compositor/DE keybind
  to `phonetic --trigger <name>` as *the* setup. No change to behavior.
- **Windows:** drop the tray/settings; run as a background process with `pynput`
  global hotkeys (already implemented) or document AutoHotkey →
  `phonetic --trigger`. Windows mic permission is per-app in Settings and rarely
  blocks.
- **macOS:** ship the same `.app`, but headless — no tray, no settings window.
  First run: `phonetic grant-mic` once (or auto-run it on first launch with a
  foreground moment). Hotkeys via Carbon (permission-free). Config by editing
  JSON or `phonetic config`.

## Consequences

### Positive
- Deletes ~900+ lines of the most fragile code and the heaviest, most
  platform-specific dependencies. The entire `pynput`-on-Sequoia,
  tkinter-before-AppKit, and tray-thread class of bugs disappears.
- One interaction model across platforms: files + a keybind. Easier to test
  (the daemon path is already the tested path) and to bundle.
- The macOS install story shrinks: still a `.app` for TCC, but no GUI frameworks
  to bundle or sign around.

### Negative / accepted
- **Onboarding gets more technical**, most sharply on macOS/Windows, where the
  GUI was the zero-config front door. A first-time non-technical user now edits a
  JSON file (or runs `phonetic config`) and binds a shortcut. `phonetic config`
  softens this but does not match a point-and-click settings window.
- **Windows/macOS gain a soft dependency on a keybind tool** where the profile's
  own hotkey isn't sufficient (AutoHotkey / skhd), mirroring the Wayland model.
- Removing the tray removes the only persistent visual affordance that the app is
  running; `phonetic doctor` and notifications become the status surface.

## Open question (needs an architect decision before implementation)

**Is a config-file-first experience (no settings GUI) acceptable for Phonetic's
target users on macOS/Windows?**

- If the audience is developer/technical: **yes** — ship CLI-first everywhere,
  this ADR stands as written.
- If non-technical desktop users matter on macOS/Windows: consider a **reduced
  middle path** — keep a *minimal* first-run permission+profile helper on macOS
  (a single AppKit window, no customtkinter) purely for the mic grant and a
  "create your first profile" step, then hand off to files. This keeps the
  hardest onboarding moment graphical without reintroducing the tray/settings
  surface.

This is the one call that can't be cheaply reversed (it decides how much GUI
code survives), so it should be made before the deletion work starts.

## Rough phasing (once the open question is resolved)
1. Extract config mutation out of `ui/settings.py` into a headless `config`
   CLI; cover with tests.
2. Add `phonetic grant-mic` / `phonetic doctor`; decouple `_check_mic_permission`
   from any tkinter init ordering.
3. Delete `tray.py`, `ui/settings.py`, GUI deps; trim `app.py` to the daemon
   pump; update `packaging/phonetic.spec`.
4. Rewrite the README setup sections per platform; update the macOS install
   chapter in `CLAUDE.md`.
