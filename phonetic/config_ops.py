"""Config-ops: the single writer for Phonetic's on-disk configuration.

A pure, UI-free, audio-free layer. Every configuration mutation — add/edit/remove
a profile, set the API key, flip a toggle — goes through here, and ONLY here. The
settings UI (``ui/settings.py``) and the ``phonetic config`` CLI are both thin
clients that call these primitives; neither assembles a ``Config`` or calls
``save_config`` itself. This single-writer discipline is what prevents the
read-path/write-path drift class of bug: one place builds the on-disk
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

Name is identity: add/edit/remove all route their result through the
``_load_profiles`` healer, which collapses blank/duplicate names and persists the
healed list. There is NO default profile: removing down to zero
profiles is a legal state and stays legal.
"""

from pathlib import Path
import os
from typing import Optional

# Import the config MODULE (not its functions by name) for everything that
# resolves a path. The per-file path helpers all derive from `config._config_dir`,
# which tests monkeypatch on the module object; a `from .config import _config_dir`
# binding would freeze the ORIGINAL at import time, so config_ops would resolve a
# different dir than the config.py readers — splitting writes across two dirs.
# Going through the module keeps a single live source of truth for the dir.
from . import config as _config
from .config import (
    Config,
    Profile,
    _format_env,
    _format_profiles_json,
    _format_settings_json,
    _load_profiles,
    _load_settings,
)
from .log import log


# ---------------------------------------------------------------------------
# Path resolution (mirrors the daemon's asymmetric read paths)
# ---------------------------------------------------------------------------


def secrets_path() -> Path:
    """Resolved .env path the daemon reads secrets from (override chain)."""
    return _config.config_file_path()


def settings_path() -> Path:
    """Platform settings.json path the daemon reads toggles from."""
    return _config._settings_path()


def profiles_path() -> Path:
    """Platform profiles.json path the daemon reads profiles from."""
    return _config._profiles_path()


def config_dir() -> Path:
    """The platform config dir (settings.json + profiles.json live here)."""
    return _config._config_dir()


# ---------------------------------------------------------------------------
# Internal per-file writers (the only places config_ops persists state)
# ---------------------------------------------------------------------------


def _write_profiles(profiles: list[Profile]) -> Path:
    """Persist the profiles list to the platform profiles.json. Returns the path.

    Mirrors ``save_config``'s profiles write exactly (same serializer, same path),
    but writes ONLY profiles.json so a profile mutation never touches .env /
    settings.json. Safe when the dir does not yet exist.
    """
    cfg_dir = _config._config_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = _config._profiles_path()
    path.write_text(_format_profiles_json(profiles), encoding="utf-8")
    return path


def _persist_through_healer(profiles: list[Profile]) -> list[Profile]:
    """Write ``profiles`` then re-read through the name-is-identity healer.

    The healer (``_load_profiles``) collapses blank/duplicate names and rewrites
    the file in place, so the post-write read is the authoritative, healed view.
    Routing every mutation through it is how name-is-identity is kept:
    no mutation bypasses the healer.
    """
    _write_profiles(profiles)
    return _load_profiles()


def _write_settings(settings: dict) -> Path:
    """Persist the toggles dict to the platform settings.json. Returns the path.

    Mirrors ``save_config``'s settings write (same serializer, same path), writing
    ONLY settings.json. Safe when the dir does not yet exist.
    """
    cfg_dir = _config._config_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = _config._settings_path()
    path.write_text(_format_settings_json(settings), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


def list_profiles() -> list[Profile]:
    """Return the configured profiles (healed). Empty list when none — never a
    synthesized default. Reads profiles.json directly; no audio, no UI."""
    return _load_profiles()


def set_profiles(profiles: list[Profile]) -> list[Profile]:
    """Replace the entire profile set and persist. Returns the healed result.

    The bulk-write primitive the settings window needs (it edits a working list
    of profiles and saves them all at once). Like every other mutation it routes
    through the healer, so blank/duplicate names are collapsed and the persisted
    list is authoritative. An empty list is legal (no default profile).
    """
    log(f"config_ops: set_profiles ({len(profiles)} profile(s))")
    return _persist_through_healer(list(profiles))


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
    for key, value in fields.items():
        setattr(target, key, value)
    healed = _persist_through_healer(profiles)
    # Locate the edited profile by INDEX, not name: the healer preserves list
    # order and only renames on a collision, so the edited profile stays at
    # ``idx``. Re-locating by name would be wrong on a rename-collision — the
    # requested name can survive on a DIFFERENT profile (an earlier-positioned
    # one keeps it; the edited one gets suffixed), so a name match would return
    # the wrong profile. Index is the positional answer we already hold.
    stored = healed[idx]
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
    path = _config.config_file_path()
    log(f"config_ops: set_api_key -> {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_format_env(api_key.strip()), encoding="utf-8")
    return path


def get_api_key() -> str:
    """Read the OpenRouter API key from the resolved secrets file (override
    chain), without polluting os.environ. Returns '' when unset. No audio, no UI.
    """
    path = _config.config_file_path()
    if not path.is_file():
        return ""
    try:
        from dotenv import dotenv_values
        return (dotenv_values(path).get("OPENROUTER_API_KEY") or "").strip()
    except Exception as exc:
        log(f"config_ops: get_api_key read failed: {exc}")
        return ""


# ---------------------------------------------------------------------------
# Toggles (settings.json)
# ---------------------------------------------------------------------------

# The bool toggle fields ``set_toggle`` writes. ``device`` is NOT here: it is an
# int index (or None) set via the config file, the tray, and auto-detect — not
# through this bool-only primitive (a CLI device-selection with enumeration is a
# separate future feature). The UI persists ``device`` via its own settings write
# in ``save_from_ui``, never through ``set_toggle``.
_BOOL_TOGGLES = frozenset({"notify", "verbose", "auto_start"})


def set_toggle(name: str, value) -> dict:
    """Set one bool settings.json toggle and persist. Returns the new settings dict.

    ``name`` is one of ``notify`` / ``verbose`` / ``auto_start`` (bool). Reads the
    merged current toggles (the file's values with NOTIFY/VERBOSE/AUTO_START env
    overrides applied, matching what the daemon loads), applies the change, writes
    settings.json only — so a process env override present at write time is
    persisted into the file. Unknown toggle names raise ``ValueError``.
    """
    if name not in _BOOL_TOGGLES:
        raise ValueError(
            f"unknown toggle {name!r}; valid: notify, verbose, auto_start"
        )
    settings = _load_settings()
    settings[name] = bool(value)
    log(f"config_ops: set_toggle {name}={settings[name]!r}")
    _write_settings(settings)
    return settings


def get_settings() -> dict:
    """Return the current toggles (notify/verbose/auto_start/device). No audio."""
    return _load_settings()


# ---------------------------------------------------------------------------
# Whole-config persistence + in-memory assembly (the settings-window surface)
# ---------------------------------------------------------------------------


def save_from_ui(
    api_key: str,
    notify: bool,
    auto_start: bool,
    profiles: list[Profile],
    *,
    sample_rate: int,
    channels: int,
    device: Optional[int],
    verbose: bool,
) -> Config:
    """Persist everything the settings window edits, then return the assembled
    in-memory Config for the app callback.

    This is the SINGLE entry point the UI uses on save: it writes the secret, the
    toggles, and the profiles each through the granular per-file writers (so the
    secrets/settings/profiles path asymmetry is honored and a CWD .env is never
    clobbered), then assembles a Config from the persisted state plus the audio
    fields the window carries. The UI never assembles a Config or calls
    save_config itself — all config logic lives here.

    ``sample_rate`` / ``channels`` / ``device`` / ``verbose`` are passed through
    from the window's existing config (they are auto-detected / not edited in the
    window) so the returned Config matches what the daemon would load.
    """
    log("config_ops: save_from_ui persisting secret + toggles + profiles")
    set_api_key(api_key)
    # Persist toggles. device + verbose are carried through unchanged from the
    # window's config; notify + auto_start are the window's checkboxes.
    settings = _load_settings()
    settings.update({
        "notify": bool(notify),
        "auto_start": bool(auto_start),
        "verbose": bool(verbose),
        "device": device,
    })
    _write_settings(settings)
    healed = set_profiles(profiles)
    return assemble_config(
        sample_rate=sample_rate, channels=channels, device=device,
        notify=bool(notify), auto_start=bool(auto_start), verbose=bool(verbose),
        profiles=healed, api_key=api_key,
    )


def assemble_config(
    *,
    sample_rate: int,
    channels: int,
    device: Optional[int],
    notify: bool,
    auto_start: bool,
    verbose: bool,
    profiles: Optional[list[Profile]] = None,
    api_key: Optional[str] = None,
) -> Config:
    """Build an in-memory Config DTO from given values (no audio detection).

    Used to hand the app a fresh Config after a UI save without going through
    load_config (which would re-detect audio). profiles/api_key default to the
    persisted values when not supplied.
    """
    return Config(
        openrouter_api_key=get_api_key() if api_key is None else api_key,
        sample_rate=sample_rate,
        channels=channels,
        device=device,
        notify=notify,
        verbose=verbose,
        auto_start=auto_start,
        profiles=_load_profiles() if profiles is None else profiles,
    )
