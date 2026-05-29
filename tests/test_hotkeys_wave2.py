"""Wave 2 hotkeys tests: update_hotkeys for pynput + signal-only managers."""
import phonetic.hotkeys as hk
from phonetic.config import Profile


class _FakeListener:
    instances = []

    def __init__(self, mapping):
        self.mapping = mapping
        self.started = False
        self.stopped = False
        self.daemon = False
        _FakeListener.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class _FakeKb:
    def GlobalHotKeys(self, mapping):  # noqa: N802 (match pynput API)
        return _FakeListener(mapping)


def test_pynput_update_hotkeys_single_listener(monkeypatch):
    _FakeListener.instances = []
    monkeypatch.setattr(hk, "_load_pynput", lambda: _FakeKb())
    monkeypatch.setattr(hk, "validate_hotkey", lambda h: None)

    mgr = hk._PynputHotkeyManager("<ctrl>+<alt>+r", on_toggle=lambda: None)
    fired = []
    profiles = [
        Profile(id="a", name="A", hotkey="<ctrl>+<alt>+a"),
        Profile(id="b", name="B", hotkey="<ctrl>+<alt>+b"),
    ]
    mgr.update_hotkeys(profiles, on_toggle_for_profile=lambda pid: fired.append(pid))

    # Exactly ONE listener created, with one mapping per profile.
    assert len(_FakeListener.instances) == 1
    listener = _FakeListener.instances[0]
    assert listener.started is True
    assert set(listener.mapping.keys()) == {"<ctrl>+<alt>+a", "<ctrl>+<alt>+b"}

    # Each mapping entry dispatches the correct profile id.
    listener.mapping["<ctrl>+<alt>+a"]()
    listener.mapping["<ctrl>+<alt>+b"]()
    assert fired == ["a", "b"]


def test_pynput_update_hotkeys_replaces_old_listener(monkeypatch):
    _FakeListener.instances = []
    monkeypatch.setattr(hk, "_load_pynput", lambda: _FakeKb())
    monkeypatch.setattr(hk, "validate_hotkey", lambda h: None)

    mgr = hk._PynputHotkeyManager("<ctrl>+<alt>+r", on_toggle=lambda: None)
    mgr.update_hotkeys([Profile(id="a", name="A", hotkey="<ctrl>+<alt>+a")], lambda pid: None)
    first = _FakeListener.instances[-1]
    mgr.update_hotkeys([Profile(id="b", name="B", hotkey="<ctrl>+<alt>+b")], lambda pid: None)

    # The previous listener was stopped; a new single one started.
    assert first.stopped is True
    assert len(_FakeListener.instances) == 2
    assert _FakeListener.instances[-1].started is True


def test_signal_only_update_hotkeys_is_noop():
    mgr = hk._SignalOnlyHotkeyManager("<ctrl>+<alt>+r", on_toggle=lambda: None)
    # Should not raise; per-profile hotkeys unsupported on Wayland.
    mgr.update_hotkeys(
        [Profile(id="a", name="A", hotkey="<ctrl>+<alt>+a")],
        on_toggle_for_profile=lambda pid: None,
    )


def test_all_managers_have_update_hotkeys():
    assert hasattr(hk._CarbonHotkeyManager, "update_hotkeys")
    assert hasattr(hk._PynputHotkeyManager, "update_hotkeys")
    assert hasattr(hk._SignalOnlyHotkeyManager, "update_hotkeys")
