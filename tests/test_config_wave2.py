"""Wave 2 config tests: profiles.json behavior under the no-default-profile model.

There is no synthesized default profile anymore: a fresh install with no
profiles.json yields an empty profile list, which the app surfaces rather than
papering over.
"""
import json

from phonetic.config import (
    Config,
    Profile,
    _profiles_path,
    load_config,
    save_config,
)


def test_no_profiles_json_yields_empty_list(isolated_config, monkeypatch):
    """No profiles.json => no profiles (NOT a synthesized default)."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    cfg = load_config(require_key=True)
    assert cfg.profiles == []


def test_duplicate_profile_ids_are_healed(isolated_config):
    """Two profiles sharing an id (corrupt config) must not collapse onto the
    first: _load_profiles reassigns fresh unique ids and persists the fix.

    Regression: a duplicated profiles.json gave both 'r' and 'c' the same id,
    so `--trigger c` (name->id) resolved back to profile r and every keybind
    produced r's output.
    """
    from phonetic.config import _load_profiles
    dup = "bb804489-6bd1-58d2-b80d-aaaeef817d07"
    _profiles_path().write_text(json.dumps({"profiles": [
        {"id": dup, "name": "r", "hotkey": "<ctrl>+<alt>+r", "system_prompt": "VIC"},
        {"id": dup, "name": "c", "hotkey": "<ctrl>+<alt>+c", "system_prompt": "PLAIN"},
    ]}), encoding="utf-8")

    profiles = _load_profiles()
    ids = [p.id for p in profiles]
    assert len(set(ids)) == 2, "ids must be unique after heal"
    assert profiles[0].id == dup, "first profile keeps the original id"
    assert profiles[1].id != dup, "the duplicate is reassigned"
    # Healed result is persisted, so a second load is already unique (idempotent).
    assert [p.id for p in _load_profiles()] == ids


def test_blank_profile_id_is_healed(isolated_config):
    from phonetic.config import _load_profiles
    _profiles_path().write_text(json.dumps({"profiles": [
        {"id": "", "name": "x", "hotkey": "<ctrl>+<alt>+x"},
    ]}), encoding="utf-8")
    assert _load_profiles()[0].id, "blank id must be replaced with a real uuid"


def test_no_default_profile_id_symbol():
    """The default-profile concept is gone; the symbol must not come back."""
    import phonetic.config as config_mod
    assert not hasattr(config_mod, "DEFAULT_PROFILE_ID")
    assert not hasattr(config_mod, "_synthesize_default_profile")


def test_save_writes_profiles_json(isolated_config, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    cfg = Config(
        openrouter_api_key="sk-test", sample_rate=48000, channels=1, device=None,
        profiles=[
            Profile(id="a", name="A", hotkey="<ctrl>+<alt>+a", model="m1"),
            Profile(id="b", name="B", hotkey="<ctrl>+<alt>+b",
                    asr_model="nvidia/parakeet-tdt-0.6b-v3",
                    format_model="openai/gpt-4o"),
        ],
    )
    save_config(cfg)
    data = json.loads(_profiles_path().read_text(encoding="utf-8"))
    assert [p["id"] for p in data["profiles"]] == ["a", "b"]
    b = next(p for p in data["profiles"] if p["id"] == "b")
    assert b["asr_model"] == "nvidia/parakeet-tdt-0.6b-v3"
    assert b["format_model"] == "openai/gpt-4o"


def test_profiles_round_trip(isolated_config, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    cfg = Config(
        openrouter_api_key="sk-test", sample_rate=48000, channels=1, device=None,
        profiles=[
            Profile(id="p1", name="One", hotkey="<ctrl>+<alt>+1", model="m"),
            Profile(id="p2", name="Two", hotkey="<ctrl>+<alt>+2", model="m2"),
        ],
    )
    save_config(cfg)
    reloaded = load_config(require_key=True)
    assert [p.id for p in reloaded.profiles] == ["p1", "p2"]
    assert reloaded.profiles[1].name == "Two"
    assert reloaded.profiles[1].model == "m2"


def test_corrupt_profiles_json_yields_empty(isolated_config, monkeypatch):
    """A corrupt profiles.json reads as 'no profiles' (logged), not a crash."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    _profiles_path().write_text("{ not valid json", encoding="utf-8")
    cfg = load_config(require_key=True)
    assert cfg.profiles == []


def test_example_files_written_on_load(isolated_config, monkeypatch):
    """Startup materializes the three .example reference files."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    load_config(require_key=True)
    names = {p.name for p in isolated_config.iterdir()}
    assert ".env.example" in names
    assert "settings.json.example" in names
    assert "profiles.json.example" in names


def test_example_profiles_have_model_and_hotkey(isolated_config, monkeypatch):
    """The profiles.json.example shows the per-profile model + hotkey shape."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    load_config(require_key=True)
    data = json.loads(
        (isolated_config / "profiles.json.example").read_text(encoding="utf-8")
    )
    for p in data["profiles"]:
        assert "model" in p
        assert "hotkey" in p
    assert set(data["_fields"]) >= {"name", "hotkey", "model", "asr_model",
                                    "format_model", "system_prompt"}
