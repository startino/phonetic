# Phonetic Project

## Architecture (v0.2.0)
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

## Workflow Preferences
- **Auto commit & push**: Always commit and push after completing work
- **Conventional commits**: Use `feat:`, `fix:`, `chore:`, `docs:` prefixes
- **Atomic commits**: Split changes into small, focused commits (e.g. new module, integration, build config as separate commits)
- **Proactive housekeeping**: Don't ignore warnings, deprecations, or stale config in tool output. If something is wrong and fixable (outdated URLs, moved repos, deprecation notices, lint warnings), fix it immediately as part of the current workflow rather than leaving it for later
- **Verify after implementing**: After completing work, always verify it succeeded to the fullest extent possible — run the code, check CI status, test imports, validate config syntax, etc. If verification reveals failures, diagnose and fix before considering the task done
- **Work autonomously**: Don't ask for confirmation on routine decisions — just do the work, verify, and report results
- **Release tags**: After every update, push a semver release tag (`git tag vX.Y.Z && git push origin vX.Y.Z`) to trigger the GitHub Actions release workflow
- **Verify CI**: After pushing, always check that GitHub Actions succeeded (`gh run list --limit 1` / `gh run view`). If a run fails, diagnose and fix before considering the task done

## Dev Commands
- `uv run phonetic` — GUI mode
- `uv run phonetic --headless` — headless/systemd mode
- `uv run phonetic --version` — version check
- `./service.sh` — systemd service management (uses `phonetic --headless`)
