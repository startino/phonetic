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

- `Ctrl+Alt+R` → clean, formatted prose
- `Ctrl+Alt+V` → **verbatim**, word-for-word with no cleanup
- `Ctrl+Alt+B` → a cheap dedicated **ASR model** for transcription, then a smart model to summarise into bullet points

Each profile has six fields:

| Field | Required | What it does |
| --- | --- | --- |
| `name` | yes | Label shown in the Settings window **and the tray menu**. Free text. |
| `hotkey` | yes | The key combo that triggers this profile, in **pynput format** (see below). Must be unique across profiles. On Wayland, bind a desktop shortcut to `phonetic --trigger <id>` instead (see [Wayland](#wayland)). |
| `model` | no | This profile's transcription model: the single-call model (when `asr_model` is empty) and the fallback formatting model. Empty → built-in default (`mistralai/voxtral-small-24b-2507`). |
| `asr_model` | no | When set, transcription becomes **two-stage**: this model does speech-to-text only (e.g. `nvidia/parakeet-tdt-0.6b-v3`), then `format_model` rewrites it. **Leave empty** for the single-model path. |
| `format_model` | no | The model that formats/cleans the two-stage transcript. Empty → falls back to this profile's `model`. Only used when `asr_model` is set. |
| `system_prompt` | no | The instruction that shapes the output (verbatim, summarised, a different language…). Empty → uses the built-in default prompt. |

> **There is no default profile, and no global model or hotkey.** Every profile carries its own `model` and `hotkey`. Recording is *only ever* started by a profile's own hotkey, by picking the profile from the tray, or via `phonetic --trigger <id>`. A trigger that names a profile which no longer exists fails loudly (a notification, no recording) rather than recording with the wrong one.

### Where the file lives

Config is split across three files in the config directory, each with an embedded `_fields` documentation block and a regenerated `*.example` sibling you can copy from:

- **`.env`** — your OpenRouter API key (secret), and nothing else.
- **`settings.json`** — app toggles: `notify`, `verbose`, `auto_start`, `device`.
- **`profiles.json`** — your profiles (each with its own model + hotkey).

| OS | Config directory |
| --- | --- |
| macOS | `~/Library/Application Support/Phonetic/` |
| Linux | `~/.config/phonetic/` |
| Windows | `%APPDATA%\Phonetic\` |

Upgrading from an older single-file `config.env`? Phonetic migrates it automatically on first launch: your key moves to `.env`, your toggles to `settings.json`, and your old `MODEL`/`HOTKEY`/prompt become your first profile in `profiles.json`.

### Two ways to configure

1. **Settings window** (easiest) — open it from the tray / menu-bar icon → **Settings**. Add a profile, name it, record its hotkey, set its model(s) and prompt, and save.
2. **Edit `profiles.json` directly** — change the file with any text editor (start from `profiles.json.example` in the same folder), then **restart Phonetic** to apply. Add as many entries to the `profiles` array as you like.

### A complete example

Three profiles: clean dictation, a verbatim hotkey, and a two-stage "bullet points" hotkey using a cheap ASR model. (The `_comment` / `_fields` keys are documentation written by Phonetic; you can leave them in place — the app ignores any key starting with `_`.)

```json
{
  "profiles": [
    {
      "id": "clean",
      "name": "Clean dictation",
      "hotkey": "<ctrl>+<alt>+r",
      "model": "mistralai/voxtral-small-24b-2507",
      "asr_model": "",
      "format_model": "",
      "system_prompt": ""
    },
    {
      "id": "verbatim",
      "name": "Verbatim",
      "hotkey": "<ctrl>+<alt>+v",
      "model": "mistralai/voxtral-small-24b-2507",
      "asr_model": "",
      "format_model": "",
      "system_prompt": "Transcribe the audio exactly as spoken, word for word. Do not remove filler words, do not fix grammar, do not reword. Only add basic punctuation."
    },
    {
      "id": "bullets",
      "name": "Bullet points",
      "hotkey": "<ctrl>+<alt>+b",
      "model": "",
      "asr_model": "nvidia/parakeet-tdt-0.6b-v3",
      "format_model": "openai/gpt-4o-mini",
      "system_prompt": "Rewrite the transcript as a concise bulleted list of the key points. Drop filler and repetition."
    }
  ]
}
```

Notes:
- **`id`** must be unique and stable — any string works (a short slug like `"verbatim"` is fine). Don't reuse an `id` between profiles. It's also the id you pass to `phonetic --trigger <id>` on Wayland.
- **No profile is privileged.** Order is just display order in the tray; there is no "primary" or "default" profile.

### Hotkey format

Hotkeys use [pynput's notation](https://pynput.readthedocs.io/en/latest/keyboard.html#pynput.keyboard.HotKey.parse): modifiers in angle brackets joined with `+`, e.g.

```
<ctrl>+<alt>+r     <cmd>+<shift>+r     <ctrl>+<alt>+<space>
```

Common modifiers: `<ctrl>`, `<alt>`, `<shift>`, `<cmd>` (macOS ⌘ / Windows key). Plain keys are written literally (`r`, `1`, `<space>`). On macOS the default is `<cmd>+<shift>+r`; on Linux/Windows it's `<ctrl>+<alt>+r`.

### Picking models

- **Single-stage (default):** leave `asr_model` empty and set `model` to a multimodal model that accepts audio — e.g. `mistralai/voxtral-small-24b-2507` (the default; chosen because OpenRouter geo-blocks OpenAI/Anthropic/Google audio for some billing regions).
- **Two-stage:** set `asr_model` to a dedicated speech-to-text model (e.g. `nvidia/parakeet-tdt-0.6b-v3`, served at OpenRouter's `/audio/transcriptions` endpoint) and `format_model` to any text model (e.g. `openai/gpt-4o-mini`). This is cheaper and often more accurate for long dictation, at the cost of one extra call.

> **Wayland:** global hotkeys can't be grabbed, but every profile still works — bind a desktop shortcut to `phonetic --trigger <id>` per profile. Full per-profile parity, no default. See the [Wayland](#wayland) section below.

## Run from source

```bash
uv run phonetic
```

For headless/server use:

```bash
uv run phonetic --headless
```

### Headless configuration

In headless mode, configuration uses the same three files as the GUI:

- **`.env`** holds only the secret:

  | Variable | Default | Description |
  |----------|---------|-------------|
  | `OPENROUTER_API_KEY` | — | Required. OpenRouter API key. |

- **`settings.json`** holds toggles: `notify`, `verbose`, `auto_start`, `device`.
- **`profiles.json`** holds your profiles — each with its own `model`, `asr_model`, `format_model`, `system_prompt`, and `hotkey`. There is no global `MODEL` or `HOTKEY` env var; transcription settings live per-profile.

Copy the regenerated `.env.example` / `settings.json.example` / `profiles.json.example` siblings as starting points. On a server where global hotkeys aren't available, trigger a profile with `phonetic --trigger <id>` (e.g. from a keybind daemon or a script).

> Toggles can still be overridden by environment variables for quick experiments: `NOTIFY`, `VERBOSE`, `AUTO_START`. Secrets and per-profile model settings are file-only.

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

Global key grabs are blocked on Wayland, so Phonetic can't listen for hotkeys directly. Instead, **each profile is triggered by its own command** — bind a desktop keyboard shortcut (in your DE's keyboard settings) per profile to:

```bash
phonetic --trigger <profile-id>
```

`<profile-id>` is the `id` field of the profile in `profiles.json` (also shown next to each profile in the Settings window, with a Copy button). This gives full per-profile parity on Wayland — every profile records with its own model and prompt, exactly like a native hotkey on X11/macOS. There is no default profile and no single shared trigger.

Under the hood, the running app listens on a control FIFO at `~/.cache/phonetic/control`; `phonetic --trigger <id>` writes the profile id to it and exits. If the app isn't running, the command prints a notice and exits non-zero (so you'll notice a misconfigured shortcut).

On X11/XWayland, profile hotkeys work directly — no per-profile commands needed.

## Clipboard

On Linux, clipboard access requires `wl-copy` (Wayland) or `xclip` (X11). On macOS and Windows, the system clipboard is used directly.

## Notifications

Desktop notifications are shown when recording starts/stops and after transcription. Disable in Settings, set `"notify": false` in `settings.json`, or set `NOTIFY=0` in the environment.
