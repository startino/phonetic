"""Wave 1 config tests: three-file split (.env / settings.json / profiles.json),
profile-centric model, and legacy config.env migration."""
import json

from phonetic.config import (
    Config,
    Profile,
    _env_path,
    _profiles_path,
    _settings_path,
    _legacy_config_env_path,
    load_config,
    save_config,
)
from phonetic.constants import DEFAULT_MODEL


def test_default_model_constant():
    # Default must stay on a provider OpenRouter does not geo-block for HK
    # billing (not OpenAI/Anthropic/Google). Mistral Voxtral is the chosen
    # default; see phonetic/constants.py and ADR 0001.
    assert DEFAULT_MODEL == "mistralai/voxtral-small-24b-2507"


def test_no_api_key_returns_none(isolated_config):
    """No secret => first-run signal (None), not a crash."""
    assert load_config(require_key=True) is None


def test_model_and_hotkey_live_on_profiles_not_env(isolated_config, monkeypatch):
    """There is no global MODEL/HOTKEY: they are per-profile only."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    cfg = load_config(require_key=True)
    assert cfg is not None
    # No global model/hotkey attributes carry meaning; profiles are the source.
    assert not hasattr(cfg, "hotkey")
    # Config.model exists only as a per-recording injection slot, blank at rest.
    assert cfg.model == ""
    # Fresh install with no profiles.json => empty profile list (no default).
    assert cfg.profiles == []


def test_save_load_round_trip(isolated_config):
    """Secrets/toggles persist; per-hotkey settings persist via profiles.json."""
    cfg = Config(
        openrouter_api_key="sk-roundtrip",
        sample_rate=48000,
        channels=1,
        device=None,
        notify=True,
        verbose=False,
        auto_start=True,
        profiles=[Profile(
            id="p1", name="Work", hotkey="<ctrl>+<alt>+r",
            model="chat/model",
            asr_model="nvidia/parakeet-tdt-0.6b-v3",
            format_model="openai/gpt-4o", system_prompt="custom prompt",
        )],
    )
    save_config(cfg)

    loaded = load_config(require_key=True)
    assert loaded.openrouter_api_key == "sk-roundtrip"
    assert loaded.auto_start is True
    assert loaded.verbose is False
    p = loaded.profiles[0]
    assert p.model == "chat/model"
    assert p.asr_model == "nvidia/parakeet-tdt-0.6b-v3"
    assert p.format_model == "openai/gpt-4o"
    assert p.system_prompt == "custom prompt"
    assert p.hotkey == "<ctrl>+<alt>+r"


def test_three_files_written(isolated_config):
    """save_config writes exactly the three new files (.env/settings/profiles)."""
    cfg = Config(
        openrouter_api_key="sk-x", sample_rate=48000, channels=1, device=None,
        profiles=[Profile(id="p1", name="A", hotkey="<ctrl>+<alt>+a", model="m")],
    )
    save_config(cfg)
    assert _env_path().is_file()
    assert _settings_path().is_file()
    assert _profiles_path().is_file()

    # .env holds the secret, nothing else interesting.
    env_text = _env_path().read_text(encoding="utf-8")
    assert "OPENROUTER_API_KEY=" in env_text
    assert "MODEL=" not in env_text
    assert "HOTKEY=" not in env_text

    # settings.json holds toggles only.
    settings = json.loads(_settings_path().read_text(encoding="utf-8"))
    assert set(["notify", "verbose", "auto_start", "device"]) <= set(settings)

    # profiles.json holds the profile with its own model + hotkey.
    profiles = json.loads(_profiles_path().read_text(encoding="utf-8"))
    assert profiles["profiles"][0]["model"] == "m"
    assert profiles["profiles"][0]["hotkey"] == "<ctrl>+<alt>+a"


def test_settings_device_override(isolated_config):
    """A device set in settings.json wins over audio auto-detect."""
    cfg = Config(
        openrouter_api_key="sk-x", sample_rate=48000, channels=1, device=3,
        profiles=[Profile(id="p1", name="A", hotkey="<ctrl>+<alt>+a")],
    )
    save_config(cfg)
    loaded = load_config(require_key=True)
    assert loaded.device == 3


# --- Legacy migration -------------------------------------------------------


def _write_legacy(cfg_dir, body):
    (cfg_dir / "config.env").write_text(body, encoding="utf-8")


def test_legacy_config_env_migrates_to_three_files(isolated_config, monkeypatch):
    """A pre-0.6.6 config.env is split into .env + settings.json + a profile."""
    _write_legacy(isolated_config, (
        'OPENROUTER_API_KEY="sk-legacy"\n'
        'MODEL="legacy/model"\n'
        'HOTKEY="<ctrl>+<alt>+r"\n'
        'NOTIFY=0\n'
        'AUTO_START=1\n'
        'SYSTEM_PROMPT="legacy prompt"\n'
    ))

    cfg = load_config(require_key=True)
    assert cfg is not None
    assert cfg.openrouter_api_key == "sk-legacy"
    assert cfg.notify is False
    assert cfg.auto_start is True

    # The old MODEL/HOTKEY/PROMPT became the user's first real profile.
    assert len(cfg.profiles) == 1
    p = cfg.profiles[0]
    assert p.model == "legacy/model"
    assert p.hotkey == "<ctrl>+<alt>+r"
    assert p.system_prompt == "legacy prompt"

    # New files exist; legacy file is left in place (harmless).
    assert _env_path().is_file()
    assert _settings_path().is_file()
    assert _profiles_path().is_file()
    assert _legacy_config_env_path().is_file()


def test_migration_does_not_clobber_existing_profiles(isolated_config, monkeypatch):
    """If profiles.json already exists, migration leaves it untouched."""
    _write_legacy(isolated_config, 'OPENROUTER_API_KEY="sk-legacy"\nMODEL="legacy/model"\n')
    _profiles_path().write_text(json.dumps({
        "profiles": [{"id": "keep", "name": "Keep", "hotkey": "<ctrl>+<alt>+k",
                      "model": "keep/model"}]
    }), encoding="utf-8")

    cfg = load_config(require_key=True)
    assert [p.id for p in cfg.profiles] == ["keep"]
    assert cfg.profiles[0].model == "keep/model"
