import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Optional

from dotenv import load_dotenv

from .constants import DEFAULT_MODEL, DEFAULT_SYSTEM_PROMPT


@dataclass
class Profile:
    """A named keybind profile: its own hotkey, models, and system prompt.

    A profile is the ONLY thing that can record. There is no default profile —
    recording is always triggered with an explicit profile id, either from this
    profile's own ``hotkey`` or by selecting it from the tray. ``model`` is the
    single-call transcription model (used when ``asr_model`` is blank) and the
    fallback formatting model; blank means fall back to the built-in default.
    """

    id: str
    name: str
    hotkey: str
    model: str = ""
    asr_model: str = ""
    format_model: str = ""
    system_prompt: str = ""


def _profile_to_dict(p: Profile) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "hotkey": p.hotkey,
        "model": p.model,
        "asr_model": p.asr_model,
        "format_model": p.format_model,
        "system_prompt": p.system_prompt,
    }


def _profile_from_dict(d: dict) -> Profile:
    return Profile(
        id=str(d.get("id") or uuid.uuid4()),
        name=str(d.get("name", "")),
        hotkey=str(d.get("hotkey", "")),
        model=str(d.get("model", "")),
        asr_model=str(d.get("asr_model", "")),
        format_model=str(d.get("format_model", "")),
        system_prompt=str(d.get("system_prompt", "")),
    )


@dataclass
class Config:
    """Runtime config aggregate, assembled from three on-disk files.

    - ``.env``         → secrets: ``openrouter_api_key``
    - ``settings.json``→ app toggles: ``notify``, ``verbose``, ``auto_start``,
                         ``device``
    - ``profiles.json``→ ``profiles`` (each carries its own model + hotkey)

    The ``model`` / ``asr_model`` / ``format_model`` / ``system_prompt`` fields
    are NOT global config — they are populated per-recording from the active
    profile at transcribe time (see app._transcribe_worker). They default blank
    here and exist only so the transcribe path has a stable shape to read.
    """

    openrouter_api_key: str
    sample_rate: int
    channels: int
    device: Optional[int]
    notify: bool = True
    verbose: bool = True
    auto_start: bool = False
    profiles: list[Profile] = field(default_factory=list)
    # Per-recording transcription fields, injected from the active profile.
    model: str = ""
    asr_model: str = ""
    format_model: str = ""
    system_prompt: str = ""

    # Fields that are auto-detected and never persisted.
    _AUTO_FIELDS: ClassVar[set[str]] = {"sample_rate", "channels"}


def _config_dir() -> Path:
    """Return platform-specific config directory."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Phonetic"
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return Path(appdata) / "Phonetic"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        return Path(xdg) / "phonetic"


def _env_path() -> Path:
    """Return path to the secrets .env file."""
    return _config_dir() / ".env"


def _legacy_config_env_path() -> Path:
    """Return path to the pre-0.6.6 combined config.env file (migration only)."""
    return _config_dir() / "config.env"


def _settings_path() -> Path:
    """Return path to the settings.json file (app toggles)."""
    return _config_dir() / "settings.json"


def _profiles_path() -> Path:
    """Return path to the sidecar profiles.json file."""
    return _config_dir() / "profiles.json"


# ---------------------------------------------------------------------------
# Legacy migration
#
# Before 0.6.6 the app stored everything in a single `config.env` (API key +
# MODEL + HOTKEY + NOTIFY + AUTO_START + SYSTEM_PROMPT). The model split that
# into three files: `.env` (secrets), `settings.json` (toggles), `profiles.json`
# (per-keybind profiles, each carrying its own model + hotkey). MODEL and HOTKEY
# no longer exist as global keys. This one-time migration preserves an existing
# user's setup: secrets/toggles move to their new homes, and — only if the user
# has no profiles yet — the old MODEL/HOTKEY/SYSTEM_PROMPT become their first
# real profile so they are never left with nothing to record with. This is data
# migration, NOT a reinstated "default profile" concept.
# ---------------------------------------------------------------------------


def _truthy(value: str) -> bool:
    return value.strip().lower() not in {"", "0", "false", "no"}


def _migrate_legacy_config_env() -> None:
    """Split a pre-0.6.6 config.env into .env + settings.json (+ a profile).

    Idempotent and conservative: never clobbers an existing new-format file,
    and leaves config.env on disk (harmless, ignored) so a downgrade still works.
    """
    legacy = _legacy_config_env_path()
    if not legacy.is_file():
        return

    # Parse the legacy file with dotenv semantics without polluting os.environ.
    try:
        from dotenv import dotenv_values
        legacy_vals = {k: (v or "") for k, v in dotenv_values(legacy).items()}
    except Exception as e:
        print(f"[config] Could not read legacy config.env: {e}", file=sys.stderr)
        return

    cfg_dir = _config_dir()
    try:
        cfg_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    # 1. Secrets → .env (only if .env doesn't already exist).
    if not _env_path().is_file():
        api_key = legacy_vals.get("OPENROUTER_API_KEY", "").strip()
        if api_key:
            try:
                _env_path().write_text(_format_env(api_key), encoding="utf-8")
            except OSError as e:
                print(f"[config] Migration: could not write .env: {e}", file=sys.stderr)

    # 2. Toggles → settings.json (only if it doesn't already exist).
    if not _settings_path().is_file():
        settings = {
            "notify": _truthy(legacy_vals.get("NOTIFY", "1")),
            "verbose": True,
            "auto_start": _truthy(legacy_vals.get("AUTO_START", "0")),
            "device": None,
        }
        try:
            _settings_path().write_text(
                _format_settings_json(settings), encoding="utf-8"
            )
        except OSError as e:
            print(f"[config] Migration: could not write settings.json: {e}", file=sys.stderr)

    # 3. If the user has no profiles yet, fold the old MODEL/HOTKEY/SYSTEM_PROMPT
    #    into a single first profile so they aren't left unable to record.
    if not _profiles_path().is_file():
        model = legacy_vals.get("MODEL", "").strip()
        hotkey = legacy_vals.get("HOTKEY", "").strip() or _default_hotkey()
        asr = legacy_vals.get("ASR_MODEL", "").strip()
        fmt = legacy_vals.get("FORMAT_MODEL", "").strip()
        prompt = legacy_vals.get("SYSTEM_PROMPT", "").strip()
        migrated = Profile(
            id=str(uuid.uuid4()),
            name="Migrated",
            hotkey=hotkey,
            model=model,
            asr_model=asr,
            format_model=fmt,
            system_prompt=prompt,
        )
        try:
            _profiles_path().write_text(
                _format_profiles_json([migrated]), encoding="utf-8"
            )
        except OSError as e:
            print(f"[config] Migration: could not write profiles.json: {e}", file=sys.stderr)


def _default_hotkey() -> str:
    return "<cmd>+<shift>+r" if sys.platform == "darwin" else "<ctrl>+<alt>+r"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _load_profiles() -> list[Profile]:
    """Read profiles.json. Returns [] when the file is absent or unreadable.

    There is NO synthesized default profile: an empty result means the user has
    not configured any profile yet, which the app surfaces (first-run wizard /
    'no profiles' notice) rather than papering over.
    """
    path = _profiles_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [_profile_from_dict(d) for d in data.get("profiles", [])]
    except Exception as e:
        print(f"[config] Could not read profiles.json: {e}", file=sys.stderr)
        return []


def _load_settings() -> dict:
    """Read settings.json toggles, falling back to defaults + env overrides."""
    notify = True
    verbose = True
    auto_start = False
    device: Optional[int] = None

    path = _settings_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            notify = bool(data.get("notify", notify))
            verbose = bool(data.get("verbose", verbose))
            auto_start = bool(data.get("auto_start", auto_start))
            dev = data.get("device", None)
            device = int(dev) if dev is not None else None
        except Exception as e:
            print(f"[config] Could not read settings.json: {e}", file=sys.stderr)

    # Env vars still override (tests + power users). Secrets stay out of here.
    if "NOTIFY" in os.environ:
        notify = _truthy(os.environ["NOTIFY"])
    if "VERBOSE" in os.environ:
        verbose = _truthy(os.environ["VERBOSE"])
    if "AUTO_START" in os.environ:
        auto_start = _truthy(os.environ["AUTO_START"])

    return {"notify": notify, "verbose": verbose,
            "auto_start": auto_start, "device": device}


def config_file_path() -> Path:
    """Return the resolved secrets file path (for UI display)."""
    env_path = os.environ.get("PHONETIC_CONFIG")
    if env_path:
        return Path(env_path)
    cwd_env = Path.cwd() / ".env"
    if cwd_env.is_file():
        return cwd_env
    return _env_path()


def _find_and_load_dotenv() -> Optional[Path]:
    """Locate and load the secrets file into os.environ. Returns the path or None.

    Resolution order: PHONETIC_CONFIG override, CWD/.env (dev), the platform
    .env, then the legacy config.env (so a not-yet-migrated install still works).
    """
    env_path = os.environ.get("PHONETIC_CONFIG")
    if env_path:
        p = Path(env_path)
        if p.is_file():
            load_dotenv(p)
            return p

    cwd_env = Path.cwd() / ".env"
    if cwd_env.is_file():
        load_dotenv(cwd_env)
        return cwd_env

    platform_env = _env_path()
    if platform_env.is_file():
        load_dotenv(platform_env)
        return platform_env

    legacy = _legacy_config_env_path()
    if legacy.is_file():
        load_dotenv(legacy)
        return legacy

    return None


def load_config(require_key: bool = True) -> Optional[Config]:
    """Load config from the three on-disk files (+ env overrides).

    Args:
        require_key: If True and no API key is found, return None (first-run).

    Returns:
        Config, or None if the API key is missing and require_key is True.
    """
    # Refresh the self-documenting .example reference files (force-rewritten on
    # every version bump), then migrate any legacy single-file config. Both run
    # first, before audio work, so they always land regardless of audio state.
    write_example_files()
    _migrate_legacy_config_env()

    from .audio_detect import detect_audio

    _find_and_load_dotenv()

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key and require_key:
        return None

    sample_rate, channels, detected_device = detect_audio()
    settings = _load_settings()
    device = settings["device"] if settings["device"] is not None else detected_device

    cfg = Config(
        openrouter_api_key=api_key,
        sample_rate=sample_rate,
        channels=channels,
        device=device,
        notify=settings["notify"],
        verbose=settings["verbose"],
        auto_start=settings["auto_start"],
        profiles=_load_profiles(),
    )
    return cfg


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _format_env(api_key: str) -> str:
    """Format the secrets-only .env file."""
    escaped = api_key.replace("\\", "\\\\").replace('"', '\\"')
    return f"""\
# phonetic secrets — see .env.example for documentation.
# This file holds ONLY secrets. App toggles live in settings.json; per-hotkey
# transcription (model, ASR/format models, prompt) lives in profiles.json.

# Required: OpenRouter API key (https://openrouter.ai/settings/keys)
OPENROUTER_API_KEY="{escaped}"
"""


def _format_settings_json(settings: dict) -> str:
    """Serialize the app-toggle settings.json, with embedded docs."""
    return json.dumps(
        {
            "_comment": _SETTINGS_HELP_COMMENT,
            "_fields": _SETTINGS_HELP_FIELDS,
            "notify": bool(settings.get("notify", True)),
            "verbose": bool(settings.get("verbose", True)),
            "auto_start": bool(settings.get("auto_start", False)),
            "device": settings.get("device", None),
        },
        indent=2,
        ensure_ascii=False,
    )


def _format_profiles_json(profiles: list[Profile]) -> str:
    """Serialize profiles to JSON text, with embedded docs."""
    return json.dumps(
        {
            "_comment": _PROFILES_HELP_COMMENT,
            "_fields": _PROFILES_HELP_FIELDS,
            "profiles": [_profile_to_dict(p) for p in profiles],
        },
        indent=2,
        ensure_ascii=False,
    )


def save_config(cfg: Config) -> Path:
    """Persist config across the three files. Returns the .env path.

    Writes .env (secret), settings.json (toggles), and profiles.json (profiles).
    """
    cfg_dir = _config_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)

    env_path = _env_path()
    env_path.write_text(_format_env(cfg.openrouter_api_key), encoding="utf-8")

    _settings_path().write_text(
        _format_settings_json({
            "notify": cfg.notify,
            "verbose": cfg.verbose,
            "auto_start": cfg.auto_start,
            "device": cfg.device,
        }),
        encoding="utf-8",
    )

    _profiles_path().write_text(
        _format_profiles_json(cfg.profiles), encoding="utf-8"
    )
    return env_path


# ---------------------------------------------------------------------------
# Embedded documentation (inert `_`-prefixed keys; the app ignores them).
# ---------------------------------------------------------------------------

_SETTINGS_HELP_COMMENT = (
    "App-wide toggles for Phonetic. Secrets live in .env; per-hotkey "
    "transcription (model, ASR/format models, system prompt) lives in "
    "profiles.json. Edit this file (or use the Settings window) and restart "
    "Phonetic to apply. Keys starting with '_' are documentation and ignored."
)

_SETTINGS_HELP_FIELDS = {
    "notify": "Desktop notifications. true = on, false = off.",
    "verbose": (
        "Verbose diagnostic logging to /tmp/phonetic_startup.log. Defaults true "
        "because bundled builds have no visible stderr and these logs are the "
        "main way to diagnose issues. Set false for a quiet log."
    ),
    "auto_start": "Launch Phonetic at login. true = on, false = off.",
    "device": (
        "Input audio device index, or null to auto-detect the system default. "
        "Usually left null; set from the tray's Audio Device menu."
    ),
}

_PROFILES_HELP_COMMENT = (
    "Per-keybind profiles for Phonetic. Each profile binds one hotkey to its "
    "own model and system prompt, so different hotkeys transcribe in different "
    "ways. There is NO default profile: recording is only ever triggered by a "
    "profile's own hotkey or by picking it from the tray. Edit this file (or "
    "use the Settings window) and restart Phonetic to apply. Keys starting with "
    "'_' are documentation and are ignored by the app. Docs: "
    "https://github.com/startino/phonetic#per-keybind-profiles"
)

_PROFILES_HELP_FIELDS = {
    "name": "Label shown in the Settings window and the tray. Free text.",
    "hotkey": (
        "Key combo that triggers this profile, in pynput format, e.g. "
        "'<ctrl>+<alt>+r' (Linux/Windows) or '<cmd>+<shift>+r' (macOS). "
        "Each profile's hotkey records and transcribes with THIS profile's "
        "settings. Hotkeys must be unique across profiles. On Wayland, where "
        "global hotkeys can't be grabbed, bind a DE shortcut to "
        "'phonetic --trigger <id>' instead (see the Settings window)."
    ),
    "model": (
        "The single-call transcription model (used when asr_model is blank), "
        "and the fallback formatting model. Must be audio-capable for the "
        "single-call path, e.g. 'mistralai/voxtral-small-24b-2507'. Blank uses "
        "the built-in default. Avoid OpenAI/Anthropic/Google providers on an "
        "HK-region billing address (OpenRouter geo-blocks all three there)."
    ),
    "asr_model": (
        "OPTIONAL. When set, transcription is two-stage: this model does "
        "speech-to-text only (e.g. 'nvidia/parakeet-tdt-0.6b-v3'), then "
        "format_model rewrites it. Leave EMPTY to use the single-call 'model'."
    ),
    "format_model": (
        "Model that formats/cleans the two-stage transcript (punctuation, "
        "paragraphs, filler removal). When empty, falls back to this profile's "
        "'model'. Only used when asr_model is set."
    ),
    "system_prompt": (
        "Instruction that shapes the output for this profile — e.g. "
        "'Transcribe verbatim.' vs 'Summarise into tight bullet points.' "
        "Empty uses the built-in default prompt."
    ),
}


# ---------------------------------------------------------------------------
# Self-documenting example files
#
# On every startup we (re)write `.env.example`, `settings.json.example`, and
# `profiles.json.example` into the config dir. They are pure REFERENCE files —
# never read by the app — showing the full range of what each setting can do.
# Force-rewritten whenever the running version changes (detected via the
# embedded `phonetic-example-v<version>` token). The live files are never
# touched here.
# ---------------------------------------------------------------------------


def _example_env_path() -> Path:
    return _config_dir() / ".env.example"


def _example_settings_path() -> Path:
    return _config_dir() / "settings.json.example"


def _example_profiles_path() -> Path:
    return _config_dir() / "profiles.json.example"


def _example_token(version: str) -> str:
    return f"phonetic-example-v{version}"


def _format_example_env(version: str) -> str:
    token = _example_token(version)
    return f"""\
# ============================================================================
# phonetic — .env.example   ({token})
# ----------------------------------------------------------------------------
# REFERENCE ONLY. Phonetic regenerates this file on every upgrade, so edits
# here WILL be overwritten. To change your real secret, edit `.env` (same
# folder) or use the Settings window, then restart Phonetic.
#
# WHAT LIVES WHERE:
#   * .env           — secrets ONLY (your OpenRouter API key). Nothing else.
#   * settings.json  — app toggles: notify, verbose, auto_start, device.
#   * profiles.json  — per-hotkey transcription: each hotkey's own model,
#                      ASR/format models, and system prompt. There is NO
#                      global MODEL or HOTKEY anymore — both live per-profile.
# ============================================================================

# Required: OpenRouter API key (https://openrouter.ai/settings/keys)
OPENROUTER_API_KEY=sk-or-v1-...
"""


def _format_example_settings_json(version: str) -> str:
    return json.dumps(
        {
            "_comment": _SETTINGS_HELP_COMMENT,
            "_note": (
                f"REFERENCE ONLY ({_example_token(version)}). Phonetic "
                "regenerates this file on every upgrade — edits here are "
                "overwritten. Copy values you want into the real settings.json "
                "(same folder) and restart."
            ),
            "_fields": _SETTINGS_HELP_FIELDS,
            "notify": True,
            "verbose": True,
            "auto_start": False,
            "device": None,
        },
        indent=2,
        ensure_ascii=False,
    )


def _example_profiles() -> list[Profile]:
    """A spread of illustrative profiles showing what's possible."""
    return [
        Profile(
            id="example-clean",
            name="Clean dictation",
            hotkey="<ctrl>+<alt>+r",
            model=DEFAULT_MODEL,
            asr_model="",
            format_model="",
            system_prompt="",  # empty -> built-in default prompt
        ),
        Profile(
            id="example-verbatim",
            name="Verbatim (no cleanup)",
            hotkey="<ctrl>+<alt>+v",
            model=DEFAULT_MODEL,
            asr_model="",
            format_model="",
            system_prompt=(
                "Transcribe the audio verbatim. Keep every word, including "
                "filler and false starts. Output only the transcription."
            ),
        ),
        Profile(
            id="example-bullets",
            name="Bullet summary (two-stage)",
            hotkey="<ctrl>+<alt>+b",
            model="",
            asr_model="nvidia/parakeet-tdt-0.6b-v3",
            format_model="mistralai/mistral-small-3.2-24b-instruct",
            system_prompt=(
                "Summarise what was said into concise, well-grouped bullet "
                "points. Drop filler. Keep the speaker's own terminology."
            ),
        ),
        Profile(
            id="example-code",
            name="Code dictation (two-stage)",
            hotkey="<ctrl>+<alt>+c",
            model="",
            asr_model="nvidia/parakeet-tdt-0.6b-v3",
            format_model="mistralai/mistral-small-3.2-24b-instruct",
            system_prompt=(
                "The speaker is dictating source code. Output the code only, "
                "inside a single fenced code block. No prose, no explanation."
            ),
        ),
    ]


def _format_example_profiles_json(version: str) -> str:
    return json.dumps(
        {
            "_comment": _PROFILES_HELP_COMMENT,
            "_note": (
                f"REFERENCE ONLY ({_example_token(version)}). Phonetic "
                "regenerates this file on every upgrade — edits here are "
                "overwritten. Copy profiles you like into the real "
                "profiles.json (same folder) and restart."
            ),
            "_fields": _PROFILES_HELP_FIELDS,
            "profiles": [_profile_to_dict(p) for p in _example_profiles()],
        },
        indent=2,
        ensure_ascii=False,
    )


def _needs_example_rewrite(path: Path, version: str) -> bool:
    """True if the example file is missing or stamped with a different version."""
    if not path.is_file():
        return True
    try:
        return _example_token(version) not in path.read_text(encoding="utf-8")
    except OSError:
        return True


def write_example_files() -> None:
    """Force-(re)write the .example reference files when the version changes.

    Called once per startup. The live .env / settings.json / profiles.json are
    never touched here — only the *.example siblings.
    """
    from . import __version__

    targets = [
        (_example_env_path(), _format_example_env(__version__)),
        (_example_settings_path(), _format_example_settings_json(__version__)),
        (_example_profiles_path(), _format_example_profiles_json(__version__)),
    ]
    for path, content in targets:
        if not _needs_example_rewrite(path, __version__):
            continue
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as e:
            print(f"[config] Could not write {path.name}: {e}", file=sys.stderr)
