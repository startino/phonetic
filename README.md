# simple-whisper

Hotkey-based speech-to-text tool using cloud Whisper (OpenAI or Azure OpenAI). Start/stop recording with a configurable keybind; transcription is copied to clipboard.

## Configure

Set environment variables (optionally via a `.env` file next to `main.py`):

- `WHISPER_PROVIDER`: `openai` or `azure` (default: `openai`)
- `HOTKEY`: Global toggle, e.g. `<ctrl>+<alt>+r` (default)
- `SAMPLE_RATE`: e.g. `16000` (default)
- `CHANNELS`: `1` mono or `2` stereo (default `1`)

For OpenAI provider:

- `OPENAI_API_KEY`: your OpenAI API key

For Azure OpenAI provider:

- `AZURE_OPENAI_ENDPOINT`: like `https://your-resource-name.openai.azure.com`
- `AZURE_OPENAI_API_KEY`: your Azure key
- `AZURE_OPENAI_DEPLOYMENT`: your Whisper deployment name
- `AZURE_OPENAI_API_VERSION`: default `2024-02-15-preview`
 - `AZURE_OPENAI_TASK`: `transcriptions` (default) or `translations`

You may also paste the full Target URI from Azure Studio into `AZURE_OPENAI_ENDPOINT`. If it already contains `/audio/transcriptions` or `/audio/translations` and an `api-version`, the app will use it as-is.

You can create a `.env` file:

```env
WHISPER_PROVIDER=openai
HOTKEY=<ctrl>+<alt>+r
SAMPLE_RATE=16000
CHANNELS=1
OPENAI_API_KEY=sk-...
```

## Run

With script installed into your environment:

```bash
uv run simple-whisper | cat
```

Or directly with Python via uv:

```bash
uv run python main.py | cat
```

The app shows: "Ready. Press <hotkey> to start/stop recording. Press <esc> to exit." Press the hotkey to toggle recording; on stop, transcription is sent to your provider and copied to the clipboard.

## Autostart as a user service (systemd)

This repo includes a convenient systemd user service. It launches the app in your session and keeps it running.

Steps (one time):

1) Ensure your `.env` is set up in the project directory.
2) Install the service and start it:

```bash
mkdir -p ~/.config/systemd/user
cp contrib/systemd/simple-whisper.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now simple-whisper.service
```

The service uses your project as WorkingDirectory and reads environment from `.env`. It runs `uv run python main.py`. On Nix systems with a dev shell, it uses that environment automatically.

## Notes

- On Linux/macOS, global hotkeys are handled by `pynput`. On Windows, the project uses the `keyboard` package (declared conditionally) but current implementation uses `pynput` for all platforms; if you prefer `keyboard` on Windows, we can switch based on OS.
- Audio is recorded via your default input device using `sounddevice` at the configured sample rate/channels and temporarily saved to a WAV file during upload.
- Errors are printed to stderr; the app keeps running so you can retry.

### Wayland (Linux)

Under Wayland, global key grabs are typically blocked for security. This app detects Wayland and exposes a signal-based toggle:

- It writes a PID file at `~/.cache/simple-whisper/pid`.
- Sending `SIGUSR1` to that PID toggles recording.

You can create a desktop shortcut or WM keybinding that runs:

```bash
kill -USR1 "$(cat ~/.cache/simple-whisper/pid)"
```

Example: bind `<ctrl>+<alt>+r` in your desktop keyboard settings to run the command above.

When running under X11/Xwayland, the app will use a global grab with your `HOTKEY` directly.

### Clipboard

This tool copies the transcript to the system clipboard using `pyperclip`. On Linux, you may need one of the following packages installed for clipboard support:

- `xclip`
- `xsel`

If neither is present, the app will print the transcription to stdout and a warning to stderr instead of failing.
