"""Wave 2 config tests: Profile sidecar JSON + default-profile synthesis."""
import json

from phonetic.config import (
    Config,
    DEFAULT_PROFILE_ID,
    Profile,
    _profiles_path,
    load_config,
    save_config,
)


def test_default_profile_id_is_deterministic():
    import uuid
    expected = str(uuid.uuid5(uuid.NAMESPACE_DNS, "phonetic-default-profile"))
    assert DEFAULT_PROFILE_ID == expected


def test_no_profiles_json_synthesizes_default(isolated_config, monkeypatch):
    """A user without profiles.json gets one synthesized default profile."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("HOTKEY", "<ctrl>+<alt>+r")
    monkeypatch.setenv("SYSTEM_PROMPT", "my prompt")
    cfg = load_config(require_key=True)
    assert len(cfg.profiles) == 1
    default = cfg.profiles[0]
    assert default.id == DEFAULT_PROFILE_ID
    assert default.name == "Default"
    assert default.hotkey == "<ctrl>+<alt>+r"
    assert default.system_prompt == "my prompt"
    assert cfg.active_profile_id == DEFAULT_PROFILE_ID


def test_synthesis_is_stable_across_loads(isolated_config, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    cfg1 = load_config(require_key=True)
    cfg2 = load_config(require_key=True)
    assert cfg1.profiles[0].id == cfg2.profiles[0].id == DEFAULT_PROFILE_ID


def test_save_writes_profiles_json(isolated_config, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    cfg = load_config(require_key=True)
    p2 = Profile(id="custom-id", name="Work", hotkey="<ctrl>+<alt>+w",
                 asr_model="nvidia/parakeet-tdt-0.6b-v3",
                 format_model="openai/gpt-4o", system_prompt="work prompt")
    cfg.profiles.append(p2)
    cfg.active_profile_id = "custom-id"
    save_config(cfg)

    data = json.loads(_profiles_path().read_text(encoding="utf-8"))
    assert data["active_profile_id"] == "custom-id"
    ids = [p["id"] for p in data["profiles"]]
    assert DEFAULT_PROFILE_ID in ids
    assert "custom-id" in ids
    work = next(p for p in data["profiles"] if p["id"] == "custom-id")
    assert work["asr_model"] == "nvidia/parakeet-tdt-0.6b-v3"
    assert work["format_model"] == "openai/gpt-4o"


def test_profiles_round_trip(isolated_config, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    cfg = load_config(require_key=True)
    cfg.profiles.append(Profile(id="p2", name="B", hotkey="<ctrl>+<alt>+b"))
    cfg.active_profile_id = "p2"
    save_config(cfg)

    reloaded = load_config(require_key=True)
    assert [p.id for p in reloaded.profiles] == [DEFAULT_PROFILE_ID, "p2"]
    assert reloaded.active_profile_id == "p2"
    assert reloaded.profiles[1].name == "B"


def test_invalid_active_id_falls_back(isolated_config, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    _profiles_path().write_text(json.dumps({
        "profiles": [{"id": "a", "name": "A", "hotkey": "<ctrl>+<alt>+a"}],
        "active_profile_id": "does-not-exist",
    }), encoding="utf-8")
    cfg = load_config(require_key=True)
    # Active id that doesn't match any profile falls back to the first profile.
    assert cfg.active_profile_id == "a"


def test_corrupt_profiles_json_synthesizes_default(isolated_config, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    _profiles_path().write_text("{ not valid json", encoding="utf-8")
    cfg = load_config(require_key=True)
    assert len(cfg.profiles) == 1
    assert cfg.profiles[0].id == DEFAULT_PROFILE_ID


def test_load_materializes_profiles_json_when_missing(isolated_config, monkeypatch):
    """First load writes a concrete, self-documenting profiles.json to disk."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("HOTKEY", "<ctrl>+<alt>+r")
    assert not _profiles_path().is_file()

    load_config(require_key=True)

    assert _profiles_path().is_file(), "profiles.json should be created on first load"
    data = json.loads(_profiles_path().read_text(encoding="utf-8"))
    # Self-documenting help block present and inert.
    assert "_comment" in data
    assert set(data["_fields"]) >= {"name", "hotkey", "asr_model",
                                    "format_model", "system_prompt"}
    # A real, editable default profile is materialized.
    assert len(data["profiles"]) == 1
    default = data["profiles"][0]
    assert default["id"] == DEFAULT_PROFILE_ID
    assert default["hotkey"] == "<ctrl>+<alt>+r"
    assert data["active_profile_id"] == DEFAULT_PROFILE_ID


def test_materialized_file_reloads_cleanly(isolated_config, monkeypatch):
    """The auto-written file (with _comment/_fields) round-trips on reload."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    load_config(require_key=True)  # materializes
    reloaded = load_config(require_key=True)  # reads it back
    assert len(reloaded.profiles) == 1
    assert reloaded.profiles[0].id == DEFAULT_PROFILE_ID
    assert reloaded.active_profile_id == DEFAULT_PROFILE_ID


def test_load_does_not_clobber_corrupt_file(isolated_config, monkeypatch):
    """A corrupt/in-progress edit is never overwritten by materialization."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    _profiles_path().write_text("{ not valid json", encoding="utf-8")
    load_config(require_key=True)
    # The bad content is preserved for the user to fix, not silently replaced.
    assert _profiles_path().read_text(encoding="utf-8") == "{ not valid json"
