import sys
import types

import pytest

import phonetic.config as config_mod


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Point config storage at a tmp dir and stub audio detection.

    Yields the tmp config directory Path so tests can inspect written files.
    """
    cfg_dir = tmp_path / "phonetic"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    # Point all config storage at the tmp dir. _config_dir is the single source
    # the per-file path helpers derive from, so overriding it relocates .env,
    # settings.json, profiles.json, and the *.example files together.
    monkeypatch.setattr(config_mod, "_config_dir", lambda: cfg_dir)

    # Stub audio_detect so load_config() never touches real hardware.
    fake_audio_detect = types.ModuleType("phonetic.audio_detect")
    fake_audio_detect.detect_audio = lambda: (48000, 1, None)
    monkeypatch.setitem(sys.modules, "phonetic.audio_detect", fake_audio_detect)

    # Prevent CWD/.env or env-var override from leaking real config in.
    monkeypatch.delenv("PHONETIC_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)

    # Clear any env vars that load_config reads so each test is deterministic.
    for var in (
        "OPENROUTER_API_KEY", "MODEL", "HOTKEY", "NOTIFY", "VERBOSE",
        "SYSTEM_PROMPT", "AUTO_START", "ASR_MODEL", "FORMAT_MODEL",
        "PHONETIC_VERBOSE",
    ):
        monkeypatch.delenv(var, raising=False)

    yield cfg_dir
