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
    clean = Profile(
        id="clean-id", name="Clean", hotkey="<ctrl>+<alt>+r",
        model="google/gemini-3-flash-preview", asr_model="", format_model="",
        system_prompt="CLEAN PROMPT",
    )
    work = Profile(
        id="work-id", name="Work", hotkey="<ctrl>+<alt>+w",
        model="", asr_model="nvidia/parakeet-tdt-0.6b-v3",
        format_model="openai/gpt-4o", system_prompt="WORK PROMPT",
    )
    return Config(
        openrouter_api_key="sk-test",
        sample_rate=16000, channels=1, device=None,
        notify=True, profiles=[clean, work],
    )


def test_resolve_profile_by_id():
    app = App(headless=True)
    app._cfg = _cfg_with_profiles()
    assert app._resolve_profile("work-id").name == "Work"
    assert app._resolve_profile("clean-id").name == "Clean"


def test_resolve_profile_by_name():
    """`phonetic --trigger <name>` (Wayland compositor binding) resolves by the
    profile's name, case-insensitively, so DE shortcuts can use a readable label
    instead of a UUID."""
    app = App(headless=True)
    app._cfg = _cfg_with_profiles()
    assert app._resolve_profile("Work").id == "work-id"
    assert app._resolve_profile("clean").id == "clean-id"
    assert app._resolve_profile("  WORK  ").id == "work-id"


def test_resolve_profile_id_wins_over_name():
    """An exact id match takes precedence over a name match."""
    app = App(headless=True)
    app._cfg = _cfg_with_profiles()
    # "work-id" is an id; must resolve by id, not be treated as a name miss.
    assert app._resolve_profile("work-id").name == "Work"


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

    app._transcribe_worker(np.zeros(100, dtype=np.float32), 16000, "work-id")
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
    app._transcribe_worker(np.zeros(100, dtype=np.float32), 16000, "work-id")
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

    app._toggle_recording("clean-id")
    assert rec.is_recording is True
    assert app._recording_profile_id == "clean-id"

    app._toggle_recording("work-id")
    assert rec.is_recording is True
    assert app._recording_profile_id == "work-id"
    assert rec._stops == 1


def test_same_profile_hotkey_while_recording_stops(monkeypatch):
    app = App(headless=True)
    app._cfg = _cfg_with_profiles()
    rec = _FakeRecorder()
    app._rec = rec
    monkeypatch.setattr(app, "_check_mic_permission", lambda: True)
    monkeypatch.setattr(app, "_notify", lambda *a, **k: None)

    app._toggle_recording("work-id")
    assert rec.is_recording is True
    app._toggle_recording("work-id")
    assert rec.is_recording is False
    assert rec._stops == 1
