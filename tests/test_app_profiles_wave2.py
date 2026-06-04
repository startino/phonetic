"""Wave 2 app tests: strict profile resolution (no default) + per-profile
transcribe routing + profile-switch-while-recording.

phonetic.app imports tkinter (and customtkinter lazily), which the host Python
lacks. We stub the GUI modules so the pure orchestration logic is importable.
"""
import sys
import types

import numpy as np
import pytest


def _install_gui_stubs():
    if "tkinter" not in sys.modules:
        tk = types.ModuleType("tkinter")
        tk.Tk = object
        tk.Event = object
        tk.PhotoImage = object
        sys.modules["tkinter"] = tk
    if "customtkinter" not in sys.modules:
        sys.modules["customtkinter"] = types.ModuleType("customtkinter")
    if "sounddevice" not in sys.modules:
        sys.modules["sounddevice"] = types.ModuleType("sounddevice")
    if "phonetic.tray" not in sys.modules:
        tray = types.ModuleType("phonetic.tray")
        tray.TrayManager = object
        tray._assets_dir = lambda: "/tmp"
        sys.modules["phonetic.tray"] = tray


_install_gui_stubs()

from phonetic.app import App, UnknownProfileError  # noqa: E402
from phonetic.config import Config, Profile  # noqa: E402


def _cfg_with_profiles():
    # The NAME is the identity; id mirrors it (id="" is overridden in __post_init__).
    clean = Profile(
        id="", name="Clean", hotkey="<ctrl>+<alt>+r",
        model="google/gemini-3-flash-preview", asr_model="", format_model="",
        system_prompt="CLEAN PROMPT",
    )
    work = Profile(
        id="", name="Work", hotkey="<ctrl>+<alt>+w",
        model="", asr_model="nvidia/parakeet-tdt-0.6b-v3",
        format_model="openai/gpt-4o", system_prompt="WORK PROMPT",
    )
    return Config(
        openrouter_api_key="sk-test",
        sample_rate=16000, channels=1, device=None,
        notify=True, profiles=[clean, work],
    )


def test_resolve_profile_by_name():
    """Profiles resolve by NAME (the identity), case-insensitive, with
    surrounding whitespace ignored -- so `phonetic --trigger Work` works."""
    app = App(headless=True)
    app._cfg = _cfg_with_profiles()
    assert app._resolve_profile("Work").name == "Work"
    assert app._resolve_profile("clean").name == "Clean"
    assert app._resolve_profile("  WORK  ").name == "Work"


def test_profile_id_mirrors_name():
    """There is no separate opaque id: id is an internal mirror of name."""
    app = App(headless=True)
    app._cfg = _cfg_with_profiles()
    for p in app._cfg.profiles:
        assert p.id == p.name


def test_resolve_profile_blank_raises():
    """No default profile: a blank id is an error, not a fallback to 'first'."""
    app = App(headless=True)
    app._cfg = _cfg_with_profiles()
    with pytest.raises(UnknownProfileError):
        app._resolve_profile("")


def test_resolve_profile_unknown_id_raises():
    app = App(headless=True)
    app._cfg = _cfg_with_profiles()
    with pytest.raises(UnknownProfileError):
        app._resolve_profile("nonexistent")


def test_transcribe_worker_uses_profile_models(monkeypatch):
    app = App(headless=True)
    app._cfg = _cfg_with_profiles()

    captured = {}

    def fake_transcribe(cfg, audio, sample_rate):
        captured["model"] = cfg.model
        captured["asr_model"] = cfg.asr_model
        captured["format_model"] = cfg.format_model
        captured["system_prompt"] = cfg.system_prompt
        return "result"

    monkeypatch.setattr("phonetic.app.transcribe", fake_transcribe)

    app._transcribe_worker(np.zeros(100, dtype=np.float32), 16000, "Work")
    assert captured["asr_model"] == "nvidia/parakeet-tdt-0.6b-v3"
    assert captured["format_model"] == "openai/gpt-4o"
    assert captured["system_prompt"] == "WORK PROMPT"
    msg = app._msg_queue.get_nowait()
    assert msg == ("transcription_done", "result")


def test_transcribe_worker_blank_model_uses_default(monkeypatch):
    from phonetic.constants import DEFAULT_MODEL
    app = App(headless=True)
    app._cfg = _cfg_with_profiles()
    captured = {}

    def fake_transcribe(cfg, audio, sample_rate):
        # Work profile leaves model blank => single-call/format model defaults.
        captured["model"] = cfg.model
        captured["format_model"] = cfg.format_model
        return "ok"

    monkeypatch.setattr("phonetic.app.transcribe", fake_transcribe)
    app._transcribe_worker(np.zeros(100, dtype=np.float32), 16000, "Work")
    assert captured["model"] == DEFAULT_MODEL
    # format_model is explicit on the work profile, so it wins.
    assert captured["format_model"] == "openai/gpt-4o"


def test_transcribe_worker_unknown_profile_posts_error(monkeypatch):
    app = App(headless=True)
    app._cfg = _cfg_with_profiles()
    monkeypatch.setattr("phonetic.app.transcribe", lambda *a: "x")
    app._transcribe_worker(np.zeros(10, dtype=np.float32), 16000, "ghost")
    cmd, payload = app._msg_queue.get_nowait()
    assert cmd == "transcription_error"


# --- profile switch while recording ---------------------------------------


class _FakeRecorder:
    def __init__(self):
        self.is_recording = False
        self.sample_rate = 16000
        self.device = None
        self._stops = 0

    def start(self):
        self.is_recording = True

    def stop(self):
        self.is_recording = False
        self._stops += 1
        return np.zeros(10, dtype=np.float32)

    def peek_level(self):
        return 0.5


def test_profile_switch_while_recording(monkeypatch):
    app = App(headless=True)
    app._cfg = _cfg_with_profiles()
    rec = _FakeRecorder()
    app._rec = rec
    monkeypatch.setattr(app, "_check_mic_permission", lambda: True)
    monkeypatch.setattr(app, "_notify", lambda *a, **k: None)

    app._toggle_recording("Clean")
    assert rec.is_recording is True
    assert app._recording_profile_id == "Clean"

    app._toggle_recording("Work")
    assert rec.is_recording is True
    assert app._recording_profile_id == "Work"
    assert rec._stops == 1


def test_same_profile_hotkey_while_recording_stops(monkeypatch):
    app = App(headless=True)
    app._cfg = _cfg_with_profiles()
    rec = _FakeRecorder()
    app._rec = rec
    monkeypatch.setattr(app, "_check_mic_permission", lambda: True)
    monkeypatch.setattr(app, "_notify", lambda *a, **k: None)

    app._toggle_recording("Work")
    assert rec.is_recording is True
    app._toggle_recording("Work")
    assert rec.is_recording is False
    assert rec._stops == 1
