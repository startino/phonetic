# phonetic

Hotkey-based speech-to-text using a multimodal LLM (Gemini via OpenRouter). Press a keybind to record, press again to stop — transcription is copied to your clipboard.

Audio is sent to a multimodal model that handles both transcription and formatting (punctuation, paragraphs, filler removal) in a single step.

## Setup

1. Get an API key from [OpenRouter](https://openrouter.ai/settings/keys)
2. Copy `.env.example` to `.env` and fill in your key:

```env
OPENROUTER_API_KEY=sk-or-v1-...
```

That's it. Sample rate and channels are auto-detected from your default microphone.

### Optional settings

Set in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL` | `google/gemini-3-flash-preview` | OpenRouter model ID |
| `HOTKEY` | `<ctrl>+<alt>+r` | Toggle keybind (X11) |
| `NOTIFY` | `1` | Desktop notifications (`0` to disable) |

## Run

```bash
uv run phonetic
```

Or directly:

```bash
uv run python main.py
```

## Autostart as a systemd user service

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

On X11/XWayland, the `HOTKEY` keybind works directly.

## Clipboard

On Linux, clipboard access requires `wl-copy` (Wayland) or `xclip` (X11). On other platforms, `pyperclip` is used.

## Notifications

On Linux, desktop notifications are sent via `notify-send` when recording starts/stops and after transcription. Set `NOTIFY=0` to disable.
