import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Optional

from dotenv import load_dotenv

from .constants import DEFAULT_MODEL, DEFAULT_SYSTEM_PROMPT

# Deterministic, stable id for the synthesized default profile so it stays the
# same across loads even before profiles.json exists.
DEFAULT_PROFILE_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "phonetic-default-profile"))


@dataclass
class Profile:
    """A named keybind profile: its own hotkey, models, and system prompt."""

    id: str
    name: str
    hotkey: str
    asr_model: str = ""
    format_model: str = ""
    system_prompt: str = ""


def _profile_to_dict(p: Profile) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "hotkey": p.hotkey,
        "asr_model": p.asr_model,
        "format_model": p.format_model,
        "system_prompt": p.system_prompt,
    }


def _profile_from_dict(d: dict) -> Profile:
    return Profile(
        id=str(d.get("id") or uuid.uuid4()),
        name=str(d.get("name", "")),
        hotkey=str(d.get("hotkey", "")),
        asr_model=str(d.get("asr_model", "")),
        format_model=str(d.get("format_model", "")),
        system_prompt=str(d.get("system_prompt", "")),
    )


@dataclass
class Config:
    openrouter_api_key: str
    model: str
    hotkey: str
    sample_rate: int
    channels: int
    device: Optional[int]
    notify: bool
    system_prompt: str
    auto_start: bool = False
    # Two-stage pipeline: when asr_model is set, transcription runs ASR then
    # formatting. When blank, the legacy single multimodal call is used.
    asr_model: str = ""
    format_model: str = ""
    # Per-keybind profiles, persisted to a sidecar profiles.json (NOT env).
    # The default profile mirrors the top-level fields for backward compat.
    profiles: list[Profile] = field(default_factory=list)

    # Fields that are auto-detected and never saved
    _AUTO_FIELDS: ClassVar[set[str]] = {"sample_rate", "channels", "device"}

    # Fields to persist
    _SAVE_FIELDS: ClassVar[set[str]] = {
        "openrouter_api_key", "model", "hotkey", "notify", "system_prompt",
        "auto_start", "asr_model", "format_model",
    }

    _FIELD_ENV_MAP: ClassVar[dict[str, str]] = {
        "openrouter_api_key": "OPENROUTER_API_KEY",
        "model": "MODEL",
        "hotkey": "HOTKEY",
        "notify": "NOTIFY",
        "system_prompt": "SYSTEM_PROMPT",
        "auto_start": "AUTO_START",
        "asr_model": "ASR_MODEL",
        "format_model": "FORMAT_MODEL",
    }


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


def _config_path() -> Path:
    """Return path to the config.env file."""
    return _config_dir() / "config.env"


def _profiles_path() -> Path:
    """Return path to the sidecar profiles.json file."""
    return _config_dir() / "profiles.json"


def _synthesize_default_profile(cfg: Config) -> Profile:
    """Build the default profile from the existing top-level config fields."""
    return Profile(
        id=DEFAULT_PROFILE_ID,
        name="Default",
        hotkey=cfg.hotkey,
        asr_model=cfg.asr_model,
        format_model=cfg.format_model,
        system_prompt=cfg.system_prompt,
    )


def _apply_profiles(cfg: Config) -> None:
    """Populate cfg.profiles from profiles.json.

    If no profiles exist on disk, synthesize one default profile from the
    top-level fields so behavior is identical for pre-profiles users. The
    first profile is the primary one — keyless triggers (tray action, Wayland
    SIGUSR1) use it.
    """
    path = _profiles_path()
    profiles: list[Profile] = []
    file_existed = path.is_file()
    if file_existed:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            profiles = [_profile_from_dict(d) for d in data.get("profiles", [])]
        except Exception as e:
            print(f"[config] Could not read profiles.json: {e}", file=sys.stderr)
            profiles = []

    if not profiles:
        profiles = [_synthesize_default_profile(cfg)]

    cfg.profiles = profiles

    # Materialize a real, self-documenting profiles.json the first time we run
    # so users have a concrete file to edit instead of a blank slate. Only when
    # the file is genuinely absent — never clobber an existing (even corrupt)
    # file, since that could be a user's edit in progress.
    if not file_existed:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_format_profiles_json(cfg), encoding="utf-8")
        except OSError as e:
            print(f"[config] Could not write profiles.json: {e}", file=sys.stderr)


def config_file_path() -> Path:
    """Return the resolved config file path (for UI display)."""
    # Check env var override
    env_path = os.environ.get("PHONETIC_CONFIG")
    if env_path:
        return Path(env_path)

    # Check CWD/.env (dev/legacy)
    cwd_env = Path.cwd() / ".env"
    if cwd_env.is_file():
        return cwd_env

    return _config_path()


def _find_and_load_dotenv() -> Optional[Path]:
    """Find and load the config file. Returns path if found, None if no config exists."""
    # 1. Env var override
    env_path = os.environ.get("PHONETIC_CONFIG")
    if env_path:
        p = Path(env_path)
        if p.is_file():
            load_dotenv(p)
            return p

    # 2. CWD/.env (dev/legacy compat)
    cwd_env = Path.cwd() / ".env"
    if cwd_env.is_file():
        load_dotenv(cwd_env)
        return cwd_env

    # 3. Platform config dir
    platform_path = _config_path()
    if platform_path.is_file():
        load_dotenv(platform_path)
        return platform_path

    return None


def load_config(require_key: bool = True) -> Optional[Config]:
    """Load config from dotenv files and environment.

    Args:
        require_key: If True and no API key found, return None instead of exiting.

    Returns:
        Config object, or None if API key is missing and require_key is True.
    """
    from .audio_detect import detect_audio

    _find_and_load_dotenv()

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key and require_key:
        return None

    sample_rate, channels, device = detect_audio()

    default_hotkey = "<cmd>+<shift>+r" if sys.platform == "darwin" else "<ctrl>+<alt>+r"

    asr_model = os.getenv("ASR_MODEL", "").strip()
    format_model = (
        os.getenv("FORMAT_MODEL", "").strip()
        or os.getenv("MODEL", DEFAULT_MODEL).strip()
    )

    cfg = Config(
        openrouter_api_key=api_key,
        model=os.getenv("MODEL", DEFAULT_MODEL).strip(),
        hotkey=os.getenv("HOTKEY", default_hotkey).strip(),
        sample_rate=sample_rate,
        channels=channels,
        device=device,
        notify=os.getenv("NOTIFY", "1").strip() not in {"0", "false", "no"},
        system_prompt=os.getenv("SYSTEM_PROMPT", "").strip() or DEFAULT_SYSTEM_PROMPT,
        auto_start=os.getenv("AUTO_START", "0").strip() not in {"0", "false", "no"},
        asr_model=asr_model,
        format_model=format_model,
    )

    # Load (or synthesize) per-keybind profiles from the sidecar JSON.
    _apply_profiles(cfg)
    return cfg


def _format_config_env(cfg: Config) -> str:
    """Format config as a commented .env file matching .env.example layout."""
    def _quote(value: object) -> str:
        if isinstance(value, bool):
            return "1" if value else "0"
        s = str(value)
        escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'

    return f"""\
# phonetic configuration
# See .env.example for full documentation.

# Required: OpenRouter API key (https://openrouter.ai/settings/keys)
OPENROUTER_API_KEY={_quote(cfg.openrouter_api_key)}

# Model to use for transcription (OpenRouter model ID)
MODEL={_quote(cfg.model)}

# ASR model for two-stage pipeline. Blank = legacy single multimodal call.
# Example: nvidia/parakeet-tdt-0.6b-v3
ASR_MODEL={_quote(cfg.asr_model)}

# Formatting model for two-stage pipeline. Blank = falls back to MODEL.
FORMAT_MODEL={_quote(cfg.format_model)}

# Hotkey (pynput format; on Wayland also supports SIGUSR1)
HOTKEY={_quote(cfg.hotkey)}

# Notifications: 1 to enable, 0 to disable
NOTIFY={_quote(cfg.notify)}

# Auto-start at login: 1 to enable, 0 to disable
AUTO_START={_quote(cfg.auto_start)}

# System prompt sent to the model (default: echoai transcription prompt)
SYSTEM_PROMPT={_quote(cfg.system_prompt)}
"""


# Embedded documentation written at the top of every profiles.json. JSON has
# no comment syntax, so we ship the docs as inert keys (the read path only
# consumes "profiles"; anything starting with "_" is ignored).
# Keeping them constant means saving never produces a spurious diff.
_PROFILES_HELP_COMMENT = (
    "Per-keybind profiles for Phonetic. Each profile binds one hotkey to its "
    "own models and system prompt, so different hotkeys can transcribe in "
    "different ways. Edit this file (or use the Settings window) and restart "
    "Phonetic to apply. Keys starting with '_' are documentation and are "
    "ignored by the app. Docs: "
    "https://github.com/startino/phonetic#per-keybind-profiles"
)

_PROFILES_HELP_FIELDS = {
    "name": "Label shown in the Settings window. Free text.",
    "hotkey": (
        "Key combo that triggers this profile, in pynput format, e.g. "
        "'<ctrl>+<alt>+r' (Linux/Windows) or '<cmd>+<shift>+r' (macOS). "
        "Each profile's hotkey records and transcribes with THIS profile's "
        "settings. Hotkeys must be unique across profiles."
    ),
    "asr_model": (
        "OPTIONAL. When set, transcription is two-stage: this model does "
        "speech-to-text only (e.g. 'nvidia/parakeet-tdt-0.6b-v3'), then "
        "format_model rewrites it. Leave EMPTY to use a single multimodal "
        "model (the legacy one-call path)."
    ),
    "format_model": (
        "Model that formats/cleans the transcript (punctuation, paragraphs, "
        "filler removal). When empty, falls back to the top-level MODEL in "
        "config.env. In single-stage mode this is the only model used."
    ),
    "system_prompt": (
        "Instruction that shapes the output for this profile — e.g. "
        "'Transcribe verbatim.' vs 'Summarise into tight bullet points.' "
        "Empty uses the built-in default prompt."
    ),
    "_order": (
        "The FIRST profile in this list is the primary one: the keyless "
        "triggers (tray/menu-bar action and the single Wayland SIGUSR1 signal) "
        "record with it. Every per-profile hotkey always uses its own profile. "
        "A hotkey registered for a profile that no longer exists fails loudly "
        "rather than recording with a fallback."
    ),
}


def _format_profiles_json(cfg: Config) -> str:
    """Serialize profiles to JSON text, with embedded docs."""
    return json.dumps(
        {
            "_comment": _PROFILES_HELP_COMMENT,
            "_fields": _PROFILES_HELP_FIELDS,
            "profiles": [_profile_to_dict(p) for p in cfg.profiles],
        },
        indent=2,
        ensure_ascii=False,
    )


def save_config(cfg: Config) -> Path:
    """Save config to the platform config path.

    Writes both config.env (top-level fields, mirroring the default profile
    for backward compat) and the sidecar profiles.json. Returns the config.env
    path written.
    """
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_format_config_env(cfg), encoding="utf-8")

    if cfg.profiles:
        _profiles_path().write_text(_format_profiles_json(cfg), encoding="utf-8")
    return path
