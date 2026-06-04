"""config_ops: the single-writer layer. Round-trips through the real config.py
primitives under the isolated_config fixture (tmp dir, no audio, no UI)."""
import phonetic.config_ops as ops
from phonetic.config import Profile, _load_profiles


def test_add_list_round_trip(isolated_config):
    assert ops.list_profiles() == []
    p = ops.add_profile("Work", hotkey="<ctrl>+<alt>+w", model="m")
    assert p.name == "Work" and p.id == p.name  # name is identity
    assert [x.name for x in ops.list_profiles()] == ["Work"]
    # survives a fresh read straight from disk via the daemon's reader.
    assert [x.name for x in _load_profiles()] == ["Work"]


def test_add_duplicate_name_is_healed(isolated_config):
    ops.add_profile("Dup")
    ops.add_profile("Dup")
    names = [p.name for p in ops.list_profiles()]
    assert names == ["Dup", "Dup (2)"]  # healer suffixes the collision.


def test_edit_renames_and_sets_fields(isolated_config):
    ops.add_profile("Work", model="old")
    stored = ops.edit_profile("Work", {"name": "Email", "model": "new"})
    assert stored.name == "Email" and stored.model == "new"
    assert [p.name for p in ops.list_profiles()] == ["Email"]


def test_edit_returns_edited_profile_on_rename_collision(isolated_config):
    """Renaming a profile onto an earlier-positioned name must return the profile
    that was ACTUALLY edited (the one the healer suffixes), not the pre-existing
    collider that keeps the requested name. profiles=[B, A]; rename A -> "B".
    """
    ops.add_profile("B", model="b-model")
    ops.add_profile("A", model="a-model")
    stored = ops.edit_profile("A", {"name": "B"})
    # The healer keeps list order: index 0 ("B") keeps the name, the edited
    # index 1 collides and becomes "B (2)". The return value must be THAT one.
    assert stored.name == "B (2)"
    assert stored.model == "a-model"  # carried over from the edited profile.
    # Persisted order is unchanged; both names present, edited one suffixed.
    assert [p.name for p in ops.list_profiles()] == ["B", "B (2)"]


def test_edit_unknown_field_raises(isolated_config):
    ops.add_profile("Work")
    try:
        ops.edit_profile("Work", {"bogus": "x"})
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unknown field")


def test_edit_missing_profile_raises_keyerror(isolated_config):
    try:
        ops.edit_profile("Ghost", {"model": "m"})
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError for missing profile")


def test_remove_to_zero_is_legal(isolated_config):
    ops.add_profile("Only")
    assert ops.remove_profile("Only") is True
    assert ops.list_profiles() == []  # no default profile re-synthesized.
    assert ops.remove_profile("Only") is False  # already gone.


def test_set_profiles_bulk_replace(isolated_config):
    ops.add_profile("A")
    healed = ops.set_profiles([
        Profile(id="", name="B", hotkey="<ctrl>+<alt>+b", model="", asr_model="",
                format_model="", system_prompt=""),
        Profile(id="", name="C", hotkey="<ctrl>+<alt>+c", model="", asr_model="",
                format_model="", system_prompt=""),
    ])
    assert [p.name for p in healed] == ["B", "C"]
    assert [p.name for p in ops.list_profiles()] == ["B", "C"]


def test_set_key_and_get_key(isolated_config):
    assert ops.get_api_key() == ""
    path = ops.set_api_key("sk-or-roundtrip")
    assert path.is_file()
    assert ops.get_api_key() == "sk-or-roundtrip"


def test_set_toggle_round_trip(isolated_config):
    ops.set_toggle("notify", False)
    assert ops.get_settings()["notify"] is False
    ops.set_toggle("auto_start", True)
    assert ops.get_settings()["auto_start"] is True


def test_set_toggle_unknown_raises(isolated_config):
    try:
        ops.set_toggle("bogus", True)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unknown toggle")


def test_save_from_ui_persists_all_and_returns_config(isolated_config):
    """The settings-window save surface: secret + toggles + profiles persisted,
    plus an assembled in-memory Config returned for the app callback."""
    profiles = [Profile(id="", name="P1", hotkey="<ctrl>+<alt>+r", model="m",
                        asr_model="", format_model="", system_prompt="s")]
    cfg = ops.save_from_ui(
        api_key="sk-or-ui", notify=False, auto_start=True, profiles=profiles,
        sample_rate=48000, channels=1, device=None, verbose=True,
    )
    # Returned DTO matches what was persisted.
    assert cfg.openrouter_api_key == "sk-or-ui"
    assert cfg.notify is False and cfg.auto_start is True
    assert [p.name for p in cfg.profiles] == ["P1"]
    assert cfg.sample_rate == 48000 and cfg.channels == 1
    # Independently persisted.
    assert ops.get_api_key() == "sk-or-ui"
    assert ops.get_settings()["notify"] is False
    assert [p.name for p in ops.list_profiles()] == ["P1"]


def test_config_path_resolution_mirrors_daemon(isolated_config):
    """settings/profiles always platform dir; secrets via the override chain."""
    cfg_dir = isolated_config  # the tmp _config_dir() the fixture installs
    assert ops.settings_path() == cfg_dir / "settings.json"
    assert ops.profiles_path() == cfg_dir / "profiles.json"
    assert ops.config_dir() == cfg_dir
    # No PHONETIC_CONFIG / CWD .env in the isolated fixture, so secrets resolve to
    # the platform .env in the same dir.
    assert ops.secrets_path() == cfg_dir / ".env"
