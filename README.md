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

A **profile** binds one hotkey to its own models and prompt. With profiles you can run several hotkeys at once — for example:

- `Ctrl+Alt+R` → clean, formatted prose (the default)
- `Ctrl+Alt+V` → **verbatim**, word-for-word with no cleanup
- `Ctrl+Alt+B` → a cheap dedicated **ASR model** for transcription, then a smart model to summarise into bullet points

Each profile has five fields:

| Field | Required | What it does |
| --- | --- | --- |
| `name` | yes | Label shown in the Settings window. Free text. |
| `hotkey` | yes | The key combo that triggers this profile, in **pynput format** (see below). Must be unique across profiles. |
| `asr_model` | no | When set, transcription becomes **two-stage**: this model does speech-to-text only (e.g. `nvidia/parakeet-tdt-0.6b-v3`), then `format_model` rewrites it. **Leave empty** for the default single-model path. |
| `format_model` | no | The model that formats/cleans the transcript. Empty → falls back to the top-level `MODEL`. In single-stage mode this is the only model used. |
| `system_prompt` | no | The instruction that shapes the output (verbatim, summarised, a different language…). Empty → uses the built-in default prompt. |

### Where the file lives — and you don't have to start from scratch

Profiles live in a `profiles.json` sidecar next to your config. **Phonetic writes this file automatically on first run**, pre-filled with your current settings as a `Default` profile and with an embedded `_fields` block documenting every key — so you always have a concrete, commented example to copy from. Just open it and edit.

| OS | Location |
| --- | --- |
| macOS | `~/Library/Application Support/Phonetic/profiles.json` |
| Linux | `~/.config/phonetic/profiles.json` |
| Windows | `%APPDATA%\Phonetic\profiles.json` |

### Two ways to configure

1. **Settings window** (easiest) — open it from the tray / menu-bar icon → **Settings**. Add a profile, name it, record its hotkey, set its models and prompt, and save.
2. **Edit `profiles.json` directly** — change the file with any text editor, then **restart Phonetic** to apply. Add as many entries to the `profiles` array as you like.

Either way, your existing single configuration becomes the `Default` profile automatically — nothing changes until you add more.

### A complete example

This adds two profiles to the auto-generated default: a verbatim hotkey, and a two-stage "bullet points" hotkey using a cheap ASR model. (The `_comment` / `_fields` keys are documentation written by Phonetic; you can leave them in place — the app ignores any key starting with `_`.)

```json
{
  "profiles": [
    {
      "id": "bb804489-6bd1-58d2-b80d-aaaeef817d07",
      "name": "Default",
      "hotkey": "<ctrl>+<alt>+r",
      "asr_model": "",
      "format_model": "mistralai/voxtral-small-24b-2507",
      "system_prompt": ""
    },
    {
      "id": "verbatim",
      "name": "Verbatim",
      "hotkey": "<ctrl>+<alt>+v",
      "asr_model": "",
      "format_model": "mistralai/voxtral-small-24b-2507",
      "system_prompt": "Transcribe the audio exactly as spoken, word for word. Do not remove filler words, do not fix grammar, do not reword. Only add basic punctuation."
    },
    {
      "id": "bullets",
      "name": "Bullet points",
      "hotkey": "<ctrl>+<alt>+b",
      "asr_model": "nvidia/parakeet-tdt-0.6b-v3",
      "format_model": "openai/gpt-4o-mini",
      "system_prompt": "Rewrite the transcript as a concise bulleted list of the key points. Drop filler and repetition."
    }
  ]
}
```

Notes:
- **`id`** must be unique and stable — any string works (the `Default` profile uses a fixed UUID; for your own profiles a short slug like `"verbatim"` is fine). Don't reuse an `id` between profiles.
- **Order matters: the first profile is the primary one.** The keyless triggers — the tray/menu-bar action and the single Wayland `SIGUSR1` signal — record with the first profile in the list. Every per-profile hotkey always uses its own profile. There is no fallback selector: a hotkey registered for a profile that no longer exists fails loudly (a notification, no recording) rather than silently recording with some other profile.

### Hotkey format

Hotkeys use [pynput's notation](https://pynput.readthedocs.io/en/latest/keyboard.html#pynput.keyboard.HotKey.parse): modifiers in angle brackets joined with `+`, e.g.

```
<ctrl>+<alt>+r     <cmd>+<shift>+r     <ctrl>+<alt>+<space>
```

Common modifiers: `<ctrl>`, `<alt>`, `<shift>`, `<cmd>` (macOS ⌘ / Windows key). Plain keys are written literally (`r`, `1`, `<space>`). On macOS the default is `<cmd>+<shift>+r`; on Linux/Windows it's `<ctrl>+<alt>+r`.

### Picking models

- **Single-stage (default):** leave `asr_model` empty and set `format_model` to a multimodal model that accepts audio — e.g. `mistralai/voxtral-small-24b-2507` (the default; chosen because OpenRouter geo-blocks OpenAI/Anthropic/Google audio for some billing regions).
- **Two-stage:** set `asr_model` to a dedicated speech-to-text model (e.g. `nvidia/parakeet-tdt-0.6b-v3`, served at OpenRouter's `/audio/transcriptions` endpoint) and `format_model` to any text model (e.g. `openai/gpt-4o-mini`). This is cheaper and often more accurate for long dictation, at the cost of one extra call.

> **Wayland caveat:** native Wayland exposes only a single global trigger (`SIGUSR1`), so just one hotkey fires there. Multiple per-profile hotkeys need X11/XWayland or macOS. See the [Wayland](#wayland) section below.

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
