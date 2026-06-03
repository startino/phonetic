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


# ---------------------------------------------------------------------------
# Self-documenting example files
#
# On every startup we (re)write `config.env.example` and `profiles.json.example`
# into the config dir. They are pure REFERENCE files — never read by the app —
# that show the full range of what each setting can do. They are force-rewritten
# whenever the running version changes (detected via the embedded
# `phonetic-example-v<version>` token), so after every upgrade the user has an
# up-to-date, richer reference sitting next to their live config. We never touch
# the user's real `config.env` / `profiles.json` here.
# ---------------------------------------------------------------------------


def _example_config_path() -> Path:
    return _config_dir() / "config.env.example"


def _example_profiles_path() -> Path:
    return _config_dir() / "profiles.json.example"


def _example_token(version: str) -> str:
    return f"phonetic-example-v{version}"


def _format_example_config_env(version: str) -> str:
    """Rich, heavily-commented config.env reference for the given version."""
    token = _example_token(version)
    return f"""\
# ============================================================================
# phonetic — config.env.example   ({token})
# ----------------------------------------------------------------------------
# REFERENCE ONLY. Phonetic regenerates this file on every upgrade, so edits
# here WILL be overwritten. To change your real settings, edit `config.env`
# (same folder) or use the Settings window, then restart Phonetic.
#
# WHAT LIVES WHERE  (important):
#   * config.env      — global app settings + the SINGLE-CALL transcription
#                       model. The keys below are the COMPLETE set Phonetic
#                       writes here.
#   * profiles.json   — per-hotkey transcription: each hotkey's own ASR model,
#                       formatting model, and system prompt. This is where the
#                       two-stage pipeline and multiple hotkeys are configured.
#                       See `profiles.json.example` in this folder.
#
# There is intentionally NO ASR_MODEL / FORMAT_MODEL / SYSTEM_PROMPT key here:
# those are per-profile now and belong in profiles.json. (Older builds wrote
# them here; for backward compatibility they are still HONORED if present in an
# existing config.env, but they no longer take effect once profiles.json exists
# — which it always does after first run — and Phonetic no longer writes them.)
# ============================================================================

# ----------------------------------------------------------------------------
# OPENROUTER_API_KEY  (REQUIRED)
#   Your OpenRouter API key. Create one at:
#     https://openrouter.ai/settings/keys
# ----------------------------------------------------------------------------
OPENROUTER_API_KEY=sk-or-v1-...

# ----------------------------------------------------------------------------
# MODEL  — the transcription model used in two situations:
#     1. The SINGLE-CALL path: any profile that leaves `asr_model` blank sends
#        audio straight to this model (must be audio-capable).
#     2. The fallback formatting model: a two-stage profile that leaves
#        `format_model` blank uses this model for its cleanup step.
#   Tips:
#     - Avoid OpenAI / Anthropic / Google providers on an HK-region billing
#       address — OpenRouter geo-blocks all three there.
#   Examples:
#     mistralai/voxtral-small-24b-2507     <- default, audio-capable, HK-safe
#     mistralai/voxtral-mini-2507          <- smaller / cheaper
#     google/gemini-2.0-flash-001          <- audio-capable (geo-limited)
# ----------------------------------------------------------------------------
MODEL={DEFAULT_MODEL}

# ----------------------------------------------------------------------------
# HOTKEY  — the PRIMARY record-toggle hotkey, in pynput format.
#   This is also the hotkey for the built-in default profile and the one the
#   tray "Start Recording" button + Wayland SIGUSR1 trigger use.
#   Modifiers: <ctrl>  <alt>  <cmd>  <shift>   (combine with '+')
#   Examples:
#     <ctrl>+<alt>+r        <- Linux / Windows default
#     <cmd>+<shift>+r       <- macOS default
#     <ctrl>+<alt>+space
#   On Wayland, recording also toggles on SIGUSR1:  kill -USR1 <pid>
#   Want SEVERAL hotkeys, each with its own models/prompt? That's what
#   profiles.json is for — see profiles.json.example.
# ----------------------------------------------------------------------------
HOTKEY=<ctrl>+<alt>+r

# ----------------------------------------------------------------------------
# NOTIFY  — desktop notifications.   1 = on, 0 = off
# ----------------------------------------------------------------------------
NOTIFY=1

# ----------------------------------------------------------------------------
# AUTO_START  — launch Phonetic at login.   1 = on, 0 = off
# ----------------------------------------------------------------------------
AUTO_START=0
"""


def _example_profiles() -> list[Profile]:
    """A spread of illustrative profiles showing what's possible."""
    return [
        Profile(
            id="example-default",
            name="Default (single-call, clean formatting)",
            hotkey="<ctrl>+<alt>+r",
            asr_model="",
            format_model="",
            system_prompt="",  # empty -> built-in default prompt
        ),
        Profile(
            id="example-verbatim",
            name="Verbatim (no cleanup)",
            hotkey="<ctrl>+<alt>+v",
            asr_model="",
            format_model="",
            system_prompt=(
                "Transcribe the audio verbatim. Keep every word, including "
                "filler and false starts. Output only the transcription."
            ),
        ),
        Profile(
            id="example-bullets",
            name="Bullet Summary (two-stage)",
            hotkey="<ctrl>+<alt>+b",
            asr_model="nvidia/parakeet-tdt-0.6b-v3",
            format_model="mistralai/mistral-small-3.2-24b-instruct",
            system_prompt=(
                "Summarise what was said into concise, well-grouped bullet "
                "points. Drop filler. Keep the speaker's own terminology."
            ),
        ),
        Profile(
            id="example-code",
            name="Code Dictation (two-stage)",
            hotkey="<ctrl>+<alt>+c",
            asr_model="nvidia/parakeet-tdt-0.6b-v3",
            format_model="mistralai/mistral-small-3.2-24b-instruct",
            system_prompt=(
                "The speaker is dictating source code. Output the code only, "
                "inside a single fenced code block. No prose, no explanation."
            ),
        ),
    ]


def _format_example_profiles_json(version: str) -> str:
    """profiles.json reference showing several distinct example profiles."""
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

    Called once per startup. The live config.env / profiles.json are never
    touched here — only the *.example siblings.
    """
    from . import __version__

    targets = [
        (_example_config_path(), _format_example_config_env(__version__)),
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
    # Refresh the self-documenting .example reference files (force-rewritten on
    # every version bump). Done first, before audio/dotenv work, so the
    # references always land regardless of audio-device or config state.
    write_example_files()

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

    # NOTE: ASR_MODEL / FORMAT_MODEL / SYSTEM_PROMPT are intentionally NOT
    # written here. They are per-profile settings (profiles.json) — the
    # transcribe path reads them from the active profile, never from these
    # top-level fields. load_config() still HONORS them if a legacy config.env
    # already contains them (back-compat), but we no longer emit them, so a
    # freshly-saved config.env stays consistent with config.env.example.
    return f"""\
# phonetic configuration
# See config.env.example (same folder) for full documentation.

# Required: OpenRouter API key (https://openrouter.ai/settings/keys)
OPENROUTER_API_KEY={_quote(cfg.openrouter_api_key)}

# Single-call transcription model + fallback formatting model (OpenRouter ID).
MODEL={_quote(cfg.model)}

# Primary record-toggle hotkey (pynput format; on Wayland also supports SIGUSR1)
HOTKEY={_quote(cfg.hotkey)}

# Notifications: 1 to enable, 0 to disable
NOTIFY={_quote(cfg.notify)}

# Auto-start at login: 1 to enable, 0 to disable
AUTO_START={_quote(cfg.auto_start)}
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
