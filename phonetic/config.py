import os
import sys
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from .constants import DEFAULT_SYSTEM_PROMPT


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

    # Fields that are auto-detected and never saved
    _AUTO_FIELDS = {"sample_rate", "channels", "device"}

    # Fields to persist
    _SAVE_FIELDS = {"openrouter_api_key", "model", "hotkey", "notify", "system_prompt", "auto_start"}

    _FIELD_ENV_MAP = {
        "openrouter_api_key": "OPENROUTER_API_KEY",
        "model": "MODEL",
        "hotkey": "HOTKEY",
        "notify": "NOTIFY",
        "system_prompt": "SYSTEM_PROMPT",
        "auto_start": "AUTO_START",
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

    return Config(
        openrouter_api_key=api_key,
        model=os.getenv("MODEL", "google/gemini-3-flash-preview").strip(),
        hotkey=os.getenv("HOTKEY", default_hotkey).strip(),
        sample_rate=sample_rate,
        channels=channels,
        device=device,
        notify=os.getenv("NOTIFY", "1").strip() not in {"0", "false", "no"},
        system_prompt=os.getenv("SYSTEM_PROMPT", "").strip() or DEFAULT_SYSTEM_PROMPT,
        auto_start=os.getenv("AUTO_START", "0").strip() not in {"0", "false", "no"},
    )


def save_config(cfg: Config) -> Path:
    """Save config fields to the platform config path. Returns the path written."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    for field_name in Config._SAVE_FIELDS:
        env_name = Config._FIELD_ENV_MAP[field_name]
        value = getattr(cfg, field_name)
        if isinstance(value, bool):
            value = "1" if value else "0"
        lines.append(f"{env_name}={value}")

    path.write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")
    return path
