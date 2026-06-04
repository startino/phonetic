# ADR 0002: v0.7 — invert to a CLI-first core with an optional UI

- Status: Accepted (direction set 2026-06-04); implementation sub-decisions
  (tray, UI toolkit) still open
- Date: 2026-06-04
- Affects: app entry point, config layer, tray, settings window. ADR 0001
  (two-stage pipeline) is unaffected.

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
(`pystray`, `customtkinter`, `Pillow`, the `pyobjc` frameworks) is the largest
and most fragile part of the build.

The deeper problem is **the dependency direction is inverted.** `app.py`'s
primary path *is* the tkinter mainloop; `--headless` is a branch off it. So the
core effectively depends on the GUI, when it should be the other way around.

**The constraint that bounds the redesign:** dropping GUI *frameworks* is not the
same as dropping the macOS `.app` bundle. macOS microphone permission (TCC)
attaches to an application's **own** bundle identity (`no.starti.phonetic`) and
the grant dialog only appears when the app is a **foreground** app.
`_check_mic_permission` (`app.py:631`) already does this with **AppKit, not
customtkinter** — `NSApplication setActivationPolicy_(Regular)` +
`activateIgnoringOtherApps_` + AVFoundation. A bare CLI launched from a terminal
would request permission under the *terminal's* identity and could not show its
own dialog. So macOS keeps a bundled `.app` and a small AppKit moment for the
one-time mic grant; it does not need a tray or a settings window.

## Decision

Invert the architecture: the **CLI/daemon is the self-sufficient core**, and any
**GUI is an optional, thin client built on top of it.**

### Core principle — the core is *areliant*; the UI is optional and one-way

- The core (daemon, config, transcribe, hotkeys, and the `phonetic` CLI verbs)
  **never imports or depends on any UI code.** Phonetic can be run and **fully
  configured** — every profile, model, hotkey, and toggle — with the UI never
  installed and never opened, using config files and `phonetic config` directly.
- The UI is a **thin client that consumes the CLI/config layer** — it "just
  happens to use the CLI": it calls the same primitives the CLI does and edits
  the same JSON files. The dependency arrow points one way only:
  **UI → core, never core → UI.**
- Core and UI are **completely separable.** The core ships and works standalone;
  the UI is an optional add-on whose presence can never change what the core can
  do. Opening the UI is always a choice, never a requirement.

### What this means for the code

- **Invert `app.py`.** The daemon event loop becomes the trunk that `main` runs.
  Launching the settings/config UI becomes an optional path that the core does
  not import at module load.
- **Give config a headless API + CLI.** Extract *all* config mutation out of
  `ui/settings.py` into pure functions in the core (`config.py` / a `config_ops`
  module) plus a `phonetic config` CLI (`list`, `add-profile`, `edit <name>`,
  `remove <name>`, `path`). The settings window owns **no** config logic of its
  own — it calls these.
- **Shrink the UI to presentation.** A configuration window that simply surfaces
  the files, plus (macOS) the first-run mic-permission grant. It carries no
  behavior the CLI lacks.
- **Keep the macOS `.app` + AppKit mic shim** (TCC needs the bundle identity + a
  foreground moment), reachable headlessly via `phonetic grant-mic` so even
  permission is not UI-gated.

### Likely dropped (separate, lower-stakes calls)

- The **pystray tray** is a persistent-process visual affordance and a source of
  background-thread bugs; it is part of the optional UI surface, not the core,
  and is a candidate for removal. Deferred as its own decision.
- Heavy GUI deps (`customtkinter`, `Pillow`, `pystray`) are kept **only** if the
  optional UI is retained; the **core build carries none of them.**

### Per-platform end state

- **Linux:** daemon + compositor/DE keybind to `phonetic --trigger <name>`
  (already the default). Optional config UI on top.
- **Windows:** background process + `pynput` global hotkeys (already implemented)
  or AutoHotkey → `phonetic --trigger`. Optional config UI on top.
- **macOS:** headless `.app`; optional config UI; first-run `phonetic grant-mic`;
  Carbon `RegisterEventHotKey` (permission-free) for hotkeys.

## Resolved decision (2026-06-04, operator)

**Keep a minimal, optional configuration UI** (plus the macOS first-run helper),
under the strict areliant principle above. The operator's framing:

> A UI intently designed for configuration of Phonetic (essentially just exposing
> the files in a UI) sounds nice. But the CLI and UI must be completely
> disconnected. I could never open the UI and still configure just by files. The
> UI just happens to use the CLI itself. The CLI should be *areliant* (not
> reliant) on the UI.

So v0.7 is **not** "delete the GUI." It is "make the core stand entirely on its
own and demote the UI to an optional client." The deletion that remains in scope
is only what is genuinely UI-only and fragile (tray) and the config *logic*
currently trapped inside `ui/settings.py`, which **moves into the core** rather
than being deleted.

Remaining sub-decisions (mine to propose, non-blocking): whether to keep the tray
at all, and whether the optional UI stays `customtkinter` or is rebuilt lighter.

## Consequences

### Positive
- The fragile parts (tray threads, tkinter-before-AppKit ordering, pynput-on-
  Sequoia, GUI bundling) stop being load-bearing — the core never touches them.
- The core is independently testable and shippable; the daemon path (already the
  tested path) becomes the only required path.
- Configuration has a real headless surface (`phonetic config`), so automation,
  servers, and dotfile-driven setups are first-class — not a GUI afterthought.

### Negative / accepted
- The UI must be **rebuilt as a pure client.** Today `ui/settings.py` owns config
  logic; pulling that into the core and leaving the window as presentation-only is
  real work, not just deletion.
- A residual GUI surface remains to maintain (the operator chose this over a
  files-only product), so the dependency/bundling cost does not go to zero on
  platforms that ship the UI.

## Implementation phasing

1. **Decouple config.** Extract all config read/write out of `ui/settings.py`
   into pure core functions + a `phonetic config` CLI; cover with tests. The UI
   keeps working but now calls these.
2. **Invert the entry point.** Make the daemon loop the trunk in `app.py`; the
   settings/permission UI becomes an optional, lazily-imported path. The core
   imports no UI module.
3. **Headless permission + status.** Add `phonetic grant-mic` and
   `phonetic doctor`; decouple `_check_mic_permission` from tkinter init ordering.
4. **Trim the optional UI.** Decide the tray's fate; shrink the settings window
   to a pure file-surfacing client; drop unused GUI deps from the core build.
5. **Docs.** Rewrite README setup per platform; update the macOS chapter in
   `CLAUDE.md`.

## Verification of the invariant

The areliant principle is testable, so it should be enforced, not just asserted:
a unit test that imports the core (`phonetic.app`, `phonetic.config`,
`phonetic.transcribe`, `phonetic.hotkeys`, the `phonetic config` CLI) with the UI
modules and GUI deps absent (or blocked in `sys.modules`) and asserts the daemon
starts and config round-trips. If the core ever imports the UI, that test fails.
