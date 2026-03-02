# Phonetic Project

## Architecture
- **Package structure**: `phonetic/` package with modules split from old monolithic `main.py`
- **Entry point**: `phonetic.__main__:main` (defined in `pyproject.toml [project.scripts]`)
- **Backward compat**: `main.py` is a shim that imports from `phonetic.__main__`
- **Modes**: GUI (tray icon via pystray + customtkinter settings) and headless (`--headless` or no display)
- **Threading**: Main thread = customtkinter mainloop, tray = daemon thread, hotkeys = pynput daemon thread, transcription = worker threads
- **Message queue**: `App._msg_queue` polled via `root.after(100, ...)` in GUI mode

## Key Modules
- `config.py` — Platform-aware config (macOS: ~/Library/Application Support/Phonetic, Windows: %APPDATA%\Phonetic, Linux: ~/.config/phonetic)
- `app.py` — Orchestrator, message dispatch, toggle_recording logic
- `tray.py` — pystray TrayManager, programmatic icon generation
- `hotkeys.py` — pynput GlobalHotKeys + SIGUSR1 fallback on Linux
- `ui/settings.py` — CTkToplevel settings window, doubles as first-run wizard
- `autostart.py` — LaunchAgent (macOS), Registry (Windows), XDG .desktop (Linux)

## Build System
- NixOS dev shell via `flake.nix` — needs `linuxHeaders` for evdev (pynput dep)
- `C_INCLUDE_PATH` must include linux headers for evdev to compile
- PyInstaller spec at `packaging/phonetic.spec`
- GitHub Actions release workflow at `.github/workflows/release.yml`

## Key Dependencies
- `pynput` (all platforms, replaced python-xlib on Linux)
- `pystray` + `Pillow` (tray icon)
- `customtkinter` (settings UI)
- `pyobjc-framework-Cocoa` + `pyobjc-framework-ApplicationServices` (macOS only)

## Code Principles
- **Single source of truth**: Never rely on a downstream layer to "fix" a wrong default. If a value should be X, set it to X at the source. Redundant overrides in UI or glue code are fragile and misleading — if the override is removed, the wrong behavior silently returns. No "it works because something else corrects it" — make the data correct where it's created.

## Workflow Preferences
- **Auto commit & push**: Always commit and push after completing work
- **Conventional commits**: Use `feat:`, `fix:`, `chore:`, `docs:` prefixes
- **Atomic commits**: Split changes into small, focused commits (e.g. new module, integration, build config as separate commits)
- **Proactive housekeeping**: Don't ignore warnings, deprecations, or stale config in tool output. If something is wrong and fixable (outdated URLs, moved repos, deprecation notices, lint warnings), fix it immediately as part of the current workflow rather than leaving it for later
- **Verify after implementing**: After completing work, always verify it succeeded to the fullest extent possible — run the code, check CI status, test imports, validate config syntax, etc. If verification reveals failures, diagnose and fix before considering the task done
- **Work autonomously**: Don't ask for confirmation on routine decisions — just do the work, verify, and report results
- **Release tags**: After every update, push a semver release tag (`git tag vX.Y.Z && git push origin vX.Y.Z`) to trigger the GitHub Actions release workflow
- **Verify CI**: After pushing, always check that GitHub Actions succeeded (`gh run list --limit 1` / `gh run view`). If a run fails, diagnose and fix before considering the task done
- **Full clean before every install test**: Always do a nuclear cleanup before installing a new build — never do partial reinstalls. User wants end-to-end verification that the full install flow works from scratch every time. See cleanup procedure below

## Debugging Methodology
- **Instrument first, fix second**: Never guess at the root cause. Add logging/diagnostics to confirm exactly where in the pipeline things break before changing any logic
- **Save intermediate artifacts**: For audio/binary pipelines, write intermediate outputs to /tmp (e.g. `/tmp/phonetic_debug.wav`) so they can be inspected independently
- **Log at each stage**: When data flows through multiple stages (record → encode → API → response), log the shape/size/key properties at each boundary to find where it degrades
- **Test the fix**: After applying a fix, actually run it and confirm the output changed, don't just assume

## macOS Install Testing

### Nuclear cleanup (run before EVERY install test)
```bash
pkill -9 -f "phonetic" 2>/dev/null; pkill -9 -f "Phonetic" 2>/dev/null
rm -rf ~/Applications/Phonetic.app /Applications/Phonetic.app
rm -rf ~/Library/Application\ Support/Phonetic ~/.config/phonetic
rm -f ~/Library/Preferences/no.starti.phonetic.plist ~/Library/Preferences/com.startino.phonetic.plist
rm -f ~/Library/LaunchAgents/no.starti.phonetic.plist ~/Library/LaunchAgents/com.startino.phonetic.plist
rm -f ~/Library/Application\ Support/CrashReporter/phonetic_*.plist
rm -f ~/Library/Logs/DiagnosticReports/phonetic-*.ips
rm -f /tmp/phonetic_startup.log /tmp/phonetic_debug.wav
rm -f ~/Downloads/Phonetic.dmg ~/Downloads/Phonetic.zip 2>/dev/null
hdiutil detach /Volumes/Phonetic 2>/dev/null; hdiutil detach "/Volumes/Phonetic 1" 2>/dev/null; hdiutil detach "/Volumes/Phonetic 2" 2>/dev/null
defaults delete com.apple.dock recent-apps 2>/dev/null; killall Dock 2>/dev/null
tccutil reset Microphone no.starti.phonetic 2>/dev/null; tccutil reset Accessibility no.starti.phonetic 2>/dev/null
tccutil reset Microphone com.startino.phonetic 2>/dev/null; tccutil reset Accessibility com.startino.phonetic 2>/dev/null
# Verify — nothing should remain outside source repo, uv cache, and claude memory
find ~ /tmp -name "*phonetic*" -o -name "*Phonetic*" 2>/dev/null | grep -v "/vcs/" | grep -v "/.cache/uv/" | grep -v "/.claude/"
```

### Install from release
```bash
gh release download vX.Y.Z --pattern "Phonetic.dmg" --dir ~/Downloads
hdiutil attach ~/Downloads/Phonetic.dmg -nobrowse
mkdir -p ~/Applications
cp -R "/Volumes/Phonetic/Phonetic.app" ~/Applications/
xattr -cr ~/Applications/Phonetic.app
open ~/Applications/Phonetic.app
```

## Dev Commands
- `uv run phonetic` — GUI mode
- `uv run phonetic --headless` — headless/systemd mode
- `uv run phonetic --version` — version check
- `./service.sh` — systemd service management (uses `phonetic --headless`)
