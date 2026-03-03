# phonetic

Hotkey-based speech-to-text using a multimodal LLM (Gemini via OpenRouter). Press a keybind to record, press again to stop — transcription is copied to your clipboard.

Audio is sent to a multimodal model that handles both transcription and formatting (punctuation, paragraphs, filler removal) in a single step.

## Install

Download the latest release from [GitHub Releases](https://github.com/startino/phonetic/releases):

| Platform | Download |
|----------|----------|
| macOS (Apple Silicon) | `Phonetic.dmg` |
| Windows | `phonetic-windows.zip` |
| Linux (Debian/Ubuntu) | `phonetic_x.x.x_amd64.deb` |

### macOS

Open the DMG, drag Phonetic to your Applications folder (or `~/Applications`), and launch it. On first run, a setup wizard will ask for your OpenRouter API key and let you configure your hotkey.

### Windows

Extract the zip and run `phonetic.exe`. The setup wizard handles configuration on first launch.

### Linux

Install the `.deb` package or run from source (see below).

## Setup

1. Get an API key from [OpenRouter](https://openrouter.ai/settings/keys)
2. Launch Phonetic — the first-run wizard will prompt for your key
3. Choose your hotkey (default: `Cmd+Shift+R` on macOS, `Ctrl+Alt+R` on Linux/Windows)
4. Press your hotkey to record, press again to stop — transcription is copied to clipboard

That's it. Sample rate and microphone are auto-detected.

## Run from source

```bash
uv run phonetic
```

For headless/server use:

```bash
uv run phonetic --headless
```

### Headless configuration

In headless mode, configure via `.env` (copy `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | — | Required. OpenRouter API key |
| `MODEL` | `google/gemini-3-flash-preview` | OpenRouter model ID |
| `HOTKEY` | `<ctrl>+<alt>+r` | Toggle keybind |
| `NOTIFY` | `1` | Desktop notifications (`0` to disable) |

## Autostart as a systemd user service (Linux)

```bash
./service.sh
```

This installs and starts the service. Other commands:

```bash
./service.sh status   # show status and logs
./service.sh remove   # stop and uninstall
```

## Wayland

Global key grabs are blocked on Wayland. The app writes a PID file at `~/.cache/phonetic/pid` and listens for `SIGUSR1`. Bind this in your desktop keyboard settings:

```bash
kill -USR1 "$(cat ~/.cache/phonetic/pid)"
```

On X11/XWayland, the hotkey keybind works directly.

## Clipboard

On Linux, clipboard access requires `wl-copy` (Wayland) or `xclip` (X11). On macOS and Windows, the system clipboard is used directly.

## Notifications

Desktop notifications are shown when recording starts/stops and after transcription. Disable in Settings or set `NOTIFY=0` in headless mode.
