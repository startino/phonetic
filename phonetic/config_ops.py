"""Config-ops: the single writer for Phonetic's on-disk configuration.

A pure, UI-free, audio-free layer. Every configuration mutation — add/edit/remove
a profile, set the API key, flip a toggle — goes through here, and ONLY here. The
settings UI (``ui/settings.py``) and the ``phonetic config`` CLI are both thin
clients that call these primitives; neither assembles a ``Config`` or calls
``save_config`` itself. This single-writer discipline is what prevents the
read-path/write-path drift class of bug (fix 0002): one place builds the on-disk
shape, so it can never diverge from what the daemon reads.

Path resolution mirrors the daemon FILE-BY-FILE (the daemon's read paths are
asymmetric, and this layer inherits the asymmetry exactly — single source of
truth: match the daemon, never "fix" an asymmetry it still has):

- **profiles.json** and **settings.json**: ALWAYS the platform ``_config_dir()``.
  ``_load_profiles`` / ``_load_settings`` read only there; ``save_config`` writes
  only there. So these ops read and write only there.
- **.env** (secrets): honor the override chain via ``config_file_path()``
  (``PHONETIC_CONFIG`` -> CWD ``.env`` -> platform ``.env``) — the IDENTICAL
  resolution the daemon's ``_find_and_load_dotenv()`` uses. A dev with a CWD
  ``.env`` must have ``config set-key`` write THAT file, not the platform one.

None of these primitives touch audio hardware: profile/settings/toggle reads go
straight to the JSON files via ``_load_profiles`` / ``_load_settings`` (never
``load_config``, which runs device detection and fails on headless boxes). Every
mutation is safe to call when the config dir / files do not yet exist (first-run
parity with the wizard) — the writers create the dir as needed.

Name is identity (fix 0007): add/edit/remove all route their result through the
``_load_profiles`` healer, which collapses blank/duplicate names and persists the
healed list. There is NO default profile (fix 0004): removing down to zero
profiles is a legal state and stays legal.
"""

from pathlib import Path
from typing import Optional

from .config import (
    Profile,
    _config_dir,
    _format_env,
    _format_profiles_json,
    _format_settings_json,
    _load_profiles,
    _load_settings,
    _profiles_path,
    _settings_path,
    config_file_path,
)
from .log import log


# ---------------------------------------------------------------------------
# Path resolution (mirrors the daemon's asymmetric read paths)
# ---------------------------------------------------------------------------


def secrets_path() -> Path:
    """Resolved .env path the daemon reads secrets from (override chain)."""
    return config_file_path()


def settings_path() -> Path:
    """Platform settings.json path the daemon reads toggles from."""
    return _settings_path()


def profiles_path() -> Path:
    """Platform profiles.json path the daemon reads profiles from."""
    return _profiles_path()


def config_dir() -> Path:
    """The platform config dir (settings.json + profiles.json live here)."""
    return _config_dir()


# ---------------------------------------------------------------------------
# Internal per-file writers (the only places config_ops persists state)
# ---------------------------------------------------------------------------


def _write_profiles(profiles: list[Profile]) -> Path:
    """Persist the profiles list to the platform profiles.json. Returns the path.

    Mirrors ``save_config``'s profiles write exactly (same serializer, same path),
    but writes ONLY profiles.json so a profile mutation never touches .env /
    settings.json. Safe when the dir does not yet exist.
    """
    cfg_dir = _config_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = _profiles_path()
    path.write_text(_format_profiles_json(profiles), encoding="utf-8")
    return path


def _persist_through_healer(profiles: list[Profile]) -> list[Profile]:
    """Write ``profiles`` then re-read through the name-is-identity healer.

    The healer (``_load_profiles``) collapses blank/duplicate names and rewrites
    the file in place, so the post-write read is the authoritative, healed view.
    Routing every mutation through it is how name-is-identity (fix 0007) is kept:
    no mutation bypasses the healer.
    """
    _write_profiles(profiles)
    return _load_profiles()


def _write_settings(settings: dict) -> Path:
    """Persist the toggles dict to the platform settings.json. Returns the path.

    Mirrors ``save_config``'s settings write (same serializer, same path), writing
    ONLY settings.json. Safe when the dir does not yet exist.
    """
    cfg_dir = _config_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = _settings_path()
    path.write_text(_format_settings_json(settings), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


def list_profiles() -> list[Profile]:
    """Return the configured profiles (healed). Empty list when none — never a
    synthesized default. Reads profiles.json directly; no audio, no UI."""
    return _load_profiles()


def add_profile(
    name: str,
    hotkey: str = "",
    model: str = "",
    asr_model: str = "",
    format_model: str = "",
    system_prompt: str = "",
) -> Profile:
    """Append a new profile and persist. Returns the healed stored profile.

    The name is the identity; a blank or duplicate name is healed (suffixed) by
    ``_load_profiles`` on the post-write read, so the returned profile carries the
    name actually stored. Safe on a non-existent config dir.
    """
    log(f"config_ops: add_profile name={name!r} hotkey={hotkey!r}")
    profiles = _load_profiles()
    new = Profile(
        id="",  # name is the identity; id is derived in __post_init__
        name=name,
        hotkey=hotkey,
        model=model,
        asr_model=asr_model,
        format_model=format_model,
        system_prompt=system_prompt,
    )
    profiles.append(new)
    healed = _persist_through_healer(profiles)
    # The new profile is the last one in append order; the healer preserves order
    # and only renames on collision, so the last entry is the one we added.
    stored = healed[-1] if healed else new
    log(f"config_ops: add_profile stored as name={stored.name!r}")
    return stored


# Fields a profile edit may set. ``name`` is editable (it is the identity, and
# renaming is a legitimate operation — the healer keeps uniqueness).
_EDITABLE_PROFILE_FIELDS = frozenset(
    {"name", "hotkey", "model", "asr_model", "format_model", "system_prompt"}
)


def _find_profile_index(profiles: list[Profile], name: str) -> Optional[int]:
    """Index of the profile whose name matches ``name`` (case-insensitive,
    whitespace-trimmed — same matching the daemon uses for --trigger)."""
    ref = name.strip().lower()
    for i, p in enumerate(profiles):
        if p.name.strip().lower() == ref:
            return i
    return None


def edit_profile(name: str, fields: dict) -> Profile:
    """Edit the named profile's fields and persist. Returns the healed profile.

    ``name`` selects the profile (by its current name); ``fields`` is a dict of
    any of ``name`` (rename), ``hotkey``, ``model``, ``asr_model``,
    ``format_model``, ``system_prompt``. ``fields`` is a dict (not ``**kwargs``)
    precisely because a rename puts ``name`` in there, which would collide with
    the positional selector. Unknown field names raise ``ValueError``. A missing
    profile raises ``KeyError``. The mutation is persisted through the healer.
    """
    unknown = set(fields) - _EDITABLE_PROFILE_FIELDS
    if unknown:
        raise ValueError(
            f"unknown profile field(s): {', '.join(sorted(unknown))}; "
            f"editable: {', '.join(sorted(_EDITABLE_PROFILE_FIELDS))}"
        )
    log(f"config_ops: edit_profile name={name!r} fields={sorted(fields)}")
    profiles = _load_profiles()
    idx = _find_profile_index(profiles, name)
    if idx is None:
        raise KeyError(name)
    target = profiles[idx]
    new_name_ref = fields.get("name", target.name)
    for key, value in fields.items():
        setattr(target, key, value)
    # Keep the id mirror in sync if the name changed (it is re-derived on load
    # anyway, but stay consistent in-memory for the post-write match).
    target.id = target.name
    healed = _persist_through_healer(profiles)
    # Re-locate by the (possibly new) name; fall back to the old name. The healer
    # may have suffixed it on a collision, so match leniently.
    new_idx = _find_profile_index(healed, new_name_ref)
    if new_idx is None:
        new_idx = _find_profile_index(healed, name)
    if new_idx is None:
        # Should not happen, but never crash: return the original position.
        new_idx = min(idx, len(healed) - 1) if healed else 0
    stored = healed[new_idx]
    log(f"config_ops: edit_profile stored as name={stored.name!r}")
    return stored


def remove_profile(name: str) -> bool:
    """Remove the named profile and persist. Returns True if one was removed.

    Removing down to ZERO profiles is a legal state (there is no default
    profile) and stays legal — the empty profiles.json is written and the daemon
    surfaces 'no profiles' rather than papering over it.
    """
    log(f"config_ops: remove_profile name={name!r}")
    profiles = _load_profiles()
    idx = _find_profile_index(profiles, name)
    if idx is None:
        log(f"config_ops: remove_profile — no profile named {name!r}")
        return False
    del profiles[idx]
    _persist_through_healer(profiles)
    log(f"config_ops: remove_profile removed {name!r}; {len(profiles)} remain")
    return True


# ---------------------------------------------------------------------------
# Secrets (.env)
# ---------------------------------------------------------------------------


def set_api_key(api_key: str) -> Path:
    """Write the OpenRouter API key to the resolved secrets file. Returns the path.

    Targets ``config_file_path()`` — the SAME .env the daemon loads (override
    chain: PHONETIC_CONFIG -> CWD/.env -> platform .env). A dev with a CWD .env
    gets that file written, not the platform one. Creates the parent dir as
    needed (e.g. first-run platform .env).
    """
    path = config_file_path()
    log(f"config_ops: set_api_key -> {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_format_env(api_key.strip()), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Toggles (settings.json)
# ---------------------------------------------------------------------------

# The toggle fields settings.json carries. ``device`` is an int index or None.
_BOOL_TOGGLES = frozenset({"notify", "verbose", "auto_start"})


def set_toggle(name: str, value) -> dict:
    """Set one settings.json toggle and persist. Returns the new settings dict.

    ``name`` is one of ``notify`` / ``verbose`` / ``auto_start`` (bool) or
    ``device`` (int index, or None to auto-detect). Reads the current toggles
    (env overrides excluded from the written file — we persist the file's own
    state plus this change), applies the change, writes settings.json only.
    Unknown toggle names raise ``ValueError``.
    """
    if name not in _BOOL_TOGGLES and name != "device":
        raise ValueError(
            f"unknown toggle {name!r}; valid: notify, verbose, auto_start, device"
        )
    settings = _load_settings()
    if name in _BOOL_TOGGLES:
        settings[name] = bool(value)
    else:  # device
        settings["device"] = int(value) if value is not None else None
    log(f"config_ops: set_toggle {name}={settings[name]!r}")
    _write_settings(settings)
    return settings


def get_settings() -> dict:
    """Return the current toggles (notify/verbose/auto_start/device). No audio."""
    return _load_settings()
