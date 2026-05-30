# phonetic

Hotkey-based speech-to-text using a multimodal LLM via OpenRouter. Press a keybind to record, press again to stop — transcription is copied to your clipboard.

By default, audio is sent to a single multimodal model (`mistralai/voxtral-small-24b-2507`) that handles both transcription and formatting (punctuation, paragraphs, filler removal) in one step. You can optionally split this into a **two-stage pipeline** — a cheap dedicated ASR model for transcription, then a separate formatting model — and configure **per-keybind profiles** so different hotkeys use different models and prompts (see below).

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

## Per-keybind profiles

You can configure **multiple keybinds, each with its own models and prompt** — for example, one hotkey that transcribes verbatim, another that cleans up rambling into tight prose, and a third that uses a cheap dedicated ASR model.

A **profile** is a named set of:

- **Hotkey** — the keybind that triggers this profile
- **ASR model** — optional; when set, transcription runs as a two-stage pipeline (this model does speech-to-text, then the format model rewrites it). Leave blank to use a single multimodal model.
- **Format model** — the model that formats/cleans the transcript (falls back to the default `MODEL` when blank)
- **System prompt** — the instruction that shapes the output (verbatim, summarised, bullet points, a different language, etc.)

**Configure them in the Settings window** (open it from the tray/menu-bar icon → Settings). Add a profile, give it a name, record its hotkey, set its models and prompt, and save. Press that profile's hotkey to record and transcribe with its settings; press a different profile's hotkey to use that one instead. Your existing single configuration becomes the "Default" profile automatically — nothing changes until you add more.

Profiles are stored in a `profiles.json` file next to your config (so they are **not** an `.env` setting):

| OS | Location |
| --- | --- |
| macOS | `~/Library/Application Support/Phonetic/profiles.json` |
| Linux | `~/.config/phonetic/profiles.json` |
| Windows | `%APPDATA%\Phonetic\profiles.json` |

Each entry has `name`, `hotkey`, `asr_model`, `format_model`, and `system_prompt`. The headless `.env` / environment variables describe only the single default keybind; multiple keybinds require the GUI (or editing `profiles.json` directly).

> Note: on Wayland, global hotkeys go through a single SIGUSR1 signal, so only one keybind fires — per-profile hotkeys need X11/XWayland or macOS. See the Wayland section below.

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
| `MODEL` | `mistralai/voxtral-small-24b-2507` | OpenRouter model ID for the single-stage / formatting call. (OpenRouter geo-blocks OpenAI/Anthropic/Google for some billing regions — the Voxtral default avoids that. If you set `MODEL` yourself, your value wins and is not overridden.) |
| `ASR_MODEL` | — | Optional. When set, enables the two-stage pipeline: this model does transcription only (e.g. `nvidia/parakeet-tdt-0.6b-v3`), then `FORMAT_MODEL` formats the text. Leave empty for the legacy single-call behavior. |
| `FORMAT_MODEL` | falls back to `MODEL` | Optional. Formatting model for stage two. Only used when `ASR_MODEL` is set. |
| `SYSTEM_PROMPT` | built-in default | Optional. Instruction prompt that shapes the formatting output. |
| `HOTKEY` | `<ctrl>+<alt>+r` | Toggle keybind |
| `NOTIFY` | `1` | Desktop notifications (`0` to disable) |
| `AUTO_START` | `0` | Start on login (`1` to enable) |

> Headless `.env` describes a **single** keybind. To run several keybinds with different models/prompts, use per-keybind profiles (below) — they're stored in `profiles.json` alongside your config, not in `.env`.

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
