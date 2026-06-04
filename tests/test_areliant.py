"""The areliant invariant test (ADR 0002 / CONTEXT.md "areliant", 1.0.0+).

*areliant* is an enforced structural property of the Phonetic core: it imports,
starts its daemon (via the extracted ``App.start()`` daemon-init path), and
performs every configuration operation with all UI modules and GUI dependencies
ABSENT from ``sys.modules`` — ``None``-blocked, not merely uninstalled. The
dependency arrow is strictly one-way: UI -> core, never core -> UI. If the core
ever imports the UI on a core path, this test fails at import.

THE SENTINEL MECHANIC IS THE CONTRACT (the trap):
- ``sys.modules["X"] = None``  =>  ``import X`` raises ImportError  (EXPOSES a
  violation). Used for the six UI names below, each as a FULLY-QUALIFIED key
  (Python checks the FQN, so a module-top ``import tkinter.messagebox`` /
  ``from PIL import Image`` would slip past a block on only the top package).
- ``types.ModuleType`` stub  =>  ``import X`` SUCCEEDS  (papers over a
  violation). Used ONLY for the core deps that are NOT UI: ``sounddevice``,
  ``soundfile``, ``httpx``, ``pynput``. ``None``-blocking any of these would be a
  false-RED that gets ``@skip``-ed within a week and kills the invariant — the
  symmetric failure to under-blocking and equally fatal. They are core (recorder
  / transcribe / hotkey backends), never UI, so they MUST stay resolvable.

A module-top GUI import anywhere in the core path makes this test FAIL — it is
NOT a smoke import. The three depths below drive: (1) import under sentinels,
(2) a config round-trip through the ops layer, (3) real daemon-init via the
extracted ``start()`` (which constructs load_config -> Recorder -> HotkeyManager
with the UI blocked).
"""
import sys
import types

import pytest

# Re-importing phonetic.app under the sentinels re-runs its module-top
# `import numpy as np`, which trips numpy's "module was reloaded" guard
# (numpy itself is never re-imported — it stays cached — but the guard fires on
# the second `import numpy` statement execution). It is a benign artifact of the
# DELIBERATE module eviction this test relies on, not a code defect. Filter it
# narrowly so the test's signal stays clean.
pytestmark = pytest.mark.filterwarnings(
    "ignore:The NumPy module was reloaded:UserWarning"
)


# The six UI names to BLOCK (assign None -> ImportError on import). Each is a
# fully-qualified sys.modules key; submodules are blocked explicitly so a
# module-top `import tkinter.messagebox` or `from PIL import Image` cannot slip
# past a block on only the parent package.
_UI_BLOCK = (
    "tkinter",
    "tkinter.messagebox",
    "customtkinter",
    "pystray",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "phonetic.ui",
    "phonetic.ui.settings",
    "phonetic.tray",
)

# Core (NON-UI) deps that must stay RESOLVABLE — never None. Native-lib-backed
# ones (sounddevice/soundfile) are stubbed as real ModuleType so a missing
# system library (e.g. PortAudio absent on a CI box) can never turn this test
# false-RED. httpx/pynput are imported for real when present (they are pure-ish
# Python and usually importable); if not, they fall back to a stub. The point is
# the same either way: these names import SUCCESSFULLY, exactly opposite to the
# UI block-set.
_CORE_STUB_ALWAYS = ("sounddevice", "soundfile")
_CORE_RESOLVE = ("httpx", "pynput")

# Core phonetic modules the test drives. They must be EVICTED before importing
# under sentinels: other test modules (e.g. test_app_profiles_wave2) import
# phonetic.app at load time WITH GUI STUBS, leaving it cached in sys.modules. If
# we didn't evict, our None-block would not re-trigger the import and the test
# would pass vacuously. Evicting forces a fresh import against the blocked UI, so
# a regressed module-top GUI import in any of them is actually caught.
#
# phonetic.config is DELIBERATELY NOT evicted: the conftest `isolated_config`
# fixture patches `_config_dir` on its module-bound reference to phonetic.config
# (captured at conftest import time). Evicting + re-importing config would make
# the test use a DIFFERENT, unpatched module object and write to the REAL config
# dir. config has no module-top UI import to catch, so keeping it cached costs
# the invariant nothing and keeps isolation intact.
_CORE_PHONETIC = (
    "phonetic.app",
    "phonetic.config_ops",
    "phonetic.transcribe",
    "phonetic.hotkeys",
    "phonetic.recorder",
    "phonetic.control",
    "phonetic.notifications",
    "phonetic.clipboard",
)


@pytest.fixture
def ui_blocked():
    """Install the areliant sentinels: UI None-blocked, core deps resolvable.

    Restoration is done by EXPLICIT snapshot/restore (try/finally), NOT via
    monkeypatch's sys.modules helpers. Reason: the test body itself re-imports
    the evicted phonetic modules, which replaces sys.modules entries; combined
    with the shared function-scoped monkeypatch used by the conftest
    isolated_config fixture, monkeypatch's LIFO restore could leave
    sys.modules["phonetic.app"] pointing at a DIFFERENT module object than the
    one a sibling test (test_app_profiles_wave2) bound its App class to at
    collection time — which would then patch the wrong module's `transcribe` and
    hit the real network. An explicit full snapshot of every key we touch, with a
    finally that rebinds each to its exact original object (or removes it if it
    was absent), guarantees sibling tests see byte-identical modules afterward.
    """
    # Snapshot the ENTIRE sys.modules mapping (shallow copy of the dict). The
    # test body re-imports the evicted phonetic modules, which transitively
    # rebinds many entries; a key-by-key snapshot of only the names we touch
    # would miss those and leave a sibling test's App class bound to a stale
    # module. Restoring the whole mapping wholesale is bulletproof: every key
    # the test added is dropped and every key it changed/removed is rebound to
    # the exact original object.
    original_modules = dict(sys.modules)
    try:
        # 1. Core deps must RESOLVE. Stub native-lib-backed ones unconditionally.
        for name in _CORE_STUB_ALWAYS:
            sys.modules[name] = types.ModuleType(name)
        # httpx/pynput: import the real module if available, else stub. Either way
        # the name resolves — it is NEVER None.
        for name in _CORE_RESOLVE:
            if sys.modules.get(name) is not None:
                continue
            try:
                __import__(name)
            except Exception:
                sys.modules[name] = types.ModuleType(name)

        # 2. Evict the core phonetic modules so the import re-runs under sentinels.
        for name in _CORE_PHONETIC:
            sys.modules.pop(name, None)

        # 3. Block the UI surface: None => ImportError on any module-top UI import.
        for name in _UI_BLOCK:
            sys.modules[name] = None

        yield
    finally:
        # Restore in place WITHOUT clear(): drop only the keys the test added,
        # and rebind only the keys whose object changed (or that the test
        # removed). A full clear() opens a transient window where sys.modules is
        # empty, which corrupts the import machinery if a daemon thread or
        # importlib bootstrap runs during it. In-place delta-restore never empties
        # the mapping.
        for name in list(sys.modules):
            if name not in original_modules:
                del sys.modules[name]
        for name, obj in original_modules.items():
            if sys.modules.get(name) is not obj:
                sys.modules[name] = obj
        # CRITICAL: also reset each restored submodule's attribute on its PARENT
        # package. Evicting + re-importing `phonetic.app` (M2) under sentinels set
        # `phonetic.app` as an attribute on the `phonetic` package object pointing
        # at M2. Restoring only sys.modules leaves the package attribute pointing
        # at the stale M2, so pytest's `monkeypatch.setattr("phonetic.app.X", ...)`
        # — which resolves via getattr(phonetic, "app") — would patch M2 while a
        # sibling test's class lives in the restored M0, hitting the real code
        # path. Rebind the parent attribute to the restored object too.
        for name, obj in original_modules.items():
            parent_name, _, child = name.rpartition(".")
            if not parent_name:
                continue
            parent = sys.modules.get(parent_name)
            if parent is not None and getattr(parent, child, None) is not obj:
                try:
                    setattr(parent, child, obj)
                except Exception:
                    pass


def _assert_ui_blocked():
    """Sanity-guard: confirm the sentinels are actually live (a None entry must
    raise ImportError). Cheap insurance that the test is testing what it claims."""
    for name in ("tkinter", "tkinter.messagebox", "customtkinter", "pystray",
                 "PIL", "PIL.Image", "phonetic.tray", "phonetic.ui.settings"):
        with pytest.raises(ImportError):
            __import__(name)


# --- Depth 1: import the core under the UI None-block --------------------------


def test_core_imports_with_ui_blocked(ui_blocked):
    """The core modules import with the entire UI surface None-blocked. Catches
    the load-bearing app.py module-top GUI import the instant it regresses."""
    _assert_ui_blocked()

    # These imports must succeed with tkinter/customtkinter/pystray/PIL/.tray/.ui
    # all raising ImportError. A module-top GUI import in any of them => failure.
    import phonetic.app  # noqa: F401
    import phonetic.config  # noqa: F401
    import phonetic.config_ops  # noqa: F401
    import phonetic.transcribe  # noqa: F401
    import phonetic.hotkeys  # noqa: F401

    from phonetic.app import App
    # Constructing the orchestrator must not touch the UI either.
    App(headless=True)


# --- Depth 2: config round-trip through the ops layer, UI absent ---------------


def test_config_round_trips_with_ui_blocked(ui_blocked, isolated_config):
    """With the UI None-blocked: add a profile via the ops layer, list reflects
    it, and it survives a save/load round-trip. Proves the shared CLI/UI config
    surface is fully reachable with zero UI present."""
    _assert_ui_blocked()

    import phonetic.config_ops as ops
    from phonetic.config import _load_profiles

    assert ops.list_profiles() == []

    stored = ops.add_profile(
        "Areliant", hotkey="<ctrl>+<alt>+a", model="test/model",
        system_prompt="ROUND TRIP",
    )
    assert stored.name == "Areliant"
    # name is identity: id mirrors name, never a separate opaque value.
    assert stored.id == stored.name

    # list reflects the add (reads profiles.json directly, no audio, no UI).
    names = [p.name for p in ops.list_profiles()]
    assert names == ["Areliant"]

    # save -> load survives: re-read straight from disk via the daemon's reader.
    reloaded = _load_profiles()
    assert [p.name for p in reloaded] == ["Areliant"]
    assert reloaded[0].hotkey == "<ctrl>+<alt>+a"
    assert reloaded[0].system_prompt == "ROUND TRIP"

    # edit + remove also reachable with the UI absent.
    ops.edit_profile("Areliant", {"name": "Renamed", "model": "test/other"})
    assert [p.name for p in ops.list_profiles()] == ["Renamed"]
    assert ops.remove_profile("Renamed") is True
    assert ops.list_profiles() == []  # remove-to-zero stays legal, no default.


# --- Depth 3: real daemon-init via the extracted start(), UI absent ------------


def test_daemon_starts_with_ui_blocked(ui_blocked, isolated_config, monkeypatch):
    """Call the EXTRACTED App.start() under sentinels. This is the step that makes
    a regressed module-top GUI import in the recorder/hotkey construction path
    actually FAIL: start() constructs the real daemon (load_config ->
    Recorder -> HotkeyManager) with the UI None-blocked, then returns before the
    message loop. The boundary deliberately INCLUDES object construction."""
    _assert_ui_blocked()

    import phonetic.config_ops as ops
    from phonetic.app import App

    # An API key is required for start() to proceed past its guard. Write it
    # through the ops layer (isolated_config has chdir'd to a tmp cwd, so the
    # secrets path resolves to the platform .env in the tmp config dir).
    ops.set_api_key("sk-or-areliant-test")
    # A profile so the daemon has something to register (also exercises the
    # hotkey-registration path with the UI blocked).
    ops.add_profile("Daemon", hotkey="<ctrl>+<alt>+d", model="test/model")

    app = App(headless=True)
    # Neutralize the background update-check thread: start() spawns it as a
    # daemon doing a real network call, which would outlive the test, make a live
    # request, and race the fixture teardown's sys.modules restore. We are
    # asserting daemon CONSTRUCTION, not the update check — stub it to a no-op so
    # no thread is spawned and the test stays hermetic and deterministic.
    monkeypatch.setattr(app, "_check_for_update", lambda: None)

    # start() must NOT block (it returns before the while-True loop) and must NOT
    # import any UI module. If it does, an ImportError from a None sentinel
    # surfaces here as a failure.
    app.start()

    # The daemon objects were actually constructed (R3: the boundary includes
    # Recorder + HotkeyManager, so depth-3 covers module-top GUI imports in that
    # construction path).
    assert app._cfg is not None
    assert app._rec is not None
    assert app._hotkeys is not None
    assert [p.name for p in app._cfg.profiles] == ["Daemon"]

    # Clean up the daemon's threads/handles so the test leaves nothing running:
    # _shutdown() stops the hotkey manager and the control channel.
    app._shutdown()
