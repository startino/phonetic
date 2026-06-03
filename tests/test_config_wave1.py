"""Wave 1 config tests: two-stage fields load/save + backward compat."""
from phonetic.config import Config, Profile, load_config, save_config
from phonetic.constants import DEFAULT_MODEL, DEFAULT_SYSTEM_PROMPT


def test_default_model_constant():
    # Default must stay on a provider OpenRouter does not geo-block for HK
    # billing (not OpenAI/Anthropic/Google). Mistral Voxtral is the chosen
    # default; see phonetic/constants.py and ADR 0001.
    assert DEFAULT_MODEL == "mistralai/voxtral-small-24b-2507"


def test_load_defaults_blank_asr_falls_back(isolated_config, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    cfg = load_config(require_key=True)
    assert cfg is not None
    # No ASR/FORMAT/MODEL env => model is default, asr blank, format = default.
    assert cfg.model == DEFAULT_MODEL
    assert cfg.asr_model == ""
    assert cfg.format_model == DEFAULT_MODEL


def test_model_only_env_backward_compat(isolated_config, monkeypatch):
    """A user with only MODEL set gets the legacy path: asr blank, format=MODEL."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("MODEL", "some/custom-model")
    cfg = load_config(require_key=True)
    assert cfg.model == "some/custom-model"
    assert cfg.asr_model == ""
    assert cfg.format_model == "some/custom-model"


def test_format_model_falls_back_to_model(isolated_config, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("MODEL", "chat/model")
    monkeypatch.setenv("ASR_MODEL", "nvidia/parakeet-tdt-0.6b-v3")
    cfg = load_config(require_key=True)
    assert cfg.asr_model == "nvidia/parakeet-tdt-0.6b-v3"
    assert cfg.format_model == "chat/model"  # falls back to MODEL


def test_explicit_format_model_used(isolated_config, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("MODEL", "chat/model")
    monkeypatch.setenv("ASR_MODEL", "nvidia/parakeet-tdt-0.6b-v3")
    monkeypatch.setenv("FORMAT_MODEL", "openai/gpt-4o")
    cfg = load_config(require_key=True)
    assert cfg.format_model == "openai/gpt-4o"


def test_save_load_round_trip(isolated_config, monkeypatch):
    """Global config.env fields round-trip; per-hotkey transcription settings
    round-trip through profiles.json, not config.env."""
    cfg = Config(
        openrouter_api_key="sk-roundtrip",
        model="chat/model",
        hotkey="<ctrl>+<alt>+r",
        sample_rate=48000,
        channels=1,
        device=None,
        notify=True,
        system_prompt="custom prompt",
        auto_start=True,
        asr_model="nvidia/parakeet-tdt-0.6b-v3",
        format_model="openai/gpt-4o",
        profiles=[Profile(
            id="p1", name="Default", hotkey="<ctrl>+<alt>+r",
            asr_model="nvidia/parakeet-tdt-0.6b-v3",
            format_model="openai/gpt-4o", system_prompt="custom prompt",
        )],
    )
    save_config(cfg)

    loaded = load_config(require_key=True)
    # Global fields persist via config.env.
    assert loaded.openrouter_api_key == "sk-roundtrip"
    assert loaded.model == "chat/model"
    assert loaded.auto_start is True
    # Per-hotkey transcription persists via profiles.json (config.env no longer
    # carries ASR_MODEL/FORMAT_MODEL/SYSTEM_PROMPT).
    assert loaded.profiles[0].asr_model == "nvidia/parakeet-tdt-0.6b-v3"
    assert loaded.profiles[0].format_model == "openai/gpt-4o"
    assert loaded.profiles[0].system_prompt == "custom prompt"


def test_save_omits_per_profile_keys_from_config_env(isolated_config):
    """config.env must NOT contain the per-profile keys — they live in
    profiles.json. Writing them to config.env would be a dead, misleading
    mirror (they are never read back at transcribe time)."""
    cfg = Config(
        openrouter_api_key="sk-x",
        model="m",
        hotkey="h",
        sample_rate=48000,
        channels=1,
        device=None,
        notify=True,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        asr_model="nvidia/parakeet-tdt-0.6b-v3",
        format_model="openai/gpt-4o",
    )
    path = save_config(cfg)
    text = path.read_text(encoding="utf-8")
    assert "ASR_MODEL=" not in text
    assert "FORMAT_MODEL=" not in text
    assert "SYSTEM_PROMPT=" not in text
    # The global single-call model is still present.
    assert "MODEL=" in text
