"""Wave 2 app tests: profile resolution + per-profile transcribe routing.

phonetic.app imports tkinter (and customtkinter lazily), which the host
Python lacks. We stub the GUI modules so the pure orchestration logic is
importable and testable.
"""
import sys
import types

import numpy as np
import pytest


def _install_gui_stubs():
    """Stub GUI / hardware modules the host Python lacks so phonetic.app imports."""
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
    # phonetic.tray needs an X display at import; stub the symbols app.py uses.
    if "phonetic.tray" not in sys.modules:
        tray = types.ModuleType("phonetic.tray")
        tray.TrayManager = object
        tray._assets_dir = lambda: "/tmp"
        sys.modules["phonetic.tray"] = tray


_install_gui_stubs()

from phonetic.app import App  # noqa: E402
from phonetic.config import Config, DEFAULT_PROFILE_ID, Profile  # noqa: E402


def _cfg_with_profiles():
    default = Profile(
        id=DEFAULT_PROFILE_ID, name="Default", hotkey="<ctrl>+<alt>+r",
        asr_model="", format_model="google/gemini-3-flash-preview",
        system_prompt="DEFAULT PROMPT",
    )
    work = Profile(
        id="work-id", name="Work", hotkey="<ctrl>+<alt>+w",
        asr_model="nvidia/parakeet-tdt-0.6b-v3", format_model="openai/gpt-4o",
        system_prompt="WORK PROMPT",
    )
    return Config(
        openrouter_api_key="sk-test",
        model="google/gemini-3-flash-preview",
        hotkey="<ctrl>+<alt>+r",
        sample_rate=16000, channels=1, device=None,
        notify=True, system_prompt="DEFAULT PROMPT",
        asr_model="", format_model="google/gemini-3-flash-preview",
        profiles=[default, work], active_profile_id=DEFAULT_PROFILE_ID,
    )


def test_resolve_profile_by_id():
    app = App(headless=True)
    app._cfg = _cfg_with_profiles()
    assert app._resolve_profile("work-id").name == "Work"
    assert app._resolve_profile(DEFAULT_PROFILE_ID).name == "Default"


def test_resolve_profile_blank_uses_active():
    app = App(headless=True)
    app._cfg = _cfg_with_profiles()
    app._cfg.active_profile_id = "work-id"
    assert app._resolve_profile("").id == "work-id"


def test_resolve_profile_unknown_id_falls_back_to_active():
    app = App(headless=True)
    app._cfg = _cfg_with_profiles()
    assert app._resolve_profile("nonexistent").id == DEFAULT_PROFILE_ID


def test_transcribe_worker_uses_profile_models(monkeypatch):
    app = App(headless=True)
    app._cfg = _cfg_with_profiles()

    captured = {}

    def fake_transcribe(cfg, audio, sample_rate):
        captured["asr_model"] = cfg.asr_model
        captured["format_model"] = cfg.format_model
        captured["system_prompt"] = cfg.system_prompt
        return "result"

    monkeypatch.setattr("phonetic.app.transcribe", fake_transcribe)

    app._transcribe_worker(np.zeros(100, dtype=np.float32), 16000, "work-id")
    assert captured["asr_model"] == "nvidia/parakeet-tdt-0.6b-v3"
    assert captured["format_model"] == "openai/gpt-4o"
    assert captured["system_prompt"] == "WORK PROMPT"
    # Result is posted back to the queue.
    msg = app._msg_queue.get_nowait()
    assert msg == ("transcription_done", "result")


def test_transcribe_worker_default_profile(monkeypatch):
    app = App(headless=True)
    app._cfg = _cfg_with_profiles()
    captured = {}

    def fake_transcribe(cfg, audio, sample_rate):
        captured["asr_model"] = cfg.asr_model
        captured["system_prompt"] = cfg.system_prompt
        return "ok"

    monkeypatch.setattr("phonetic.app.transcribe", fake_transcribe)
    app._transcribe_worker(np.zeros(100, dtype=np.float32), 16000, DEFAULT_PROFILE_ID)
    # Default profile => legacy single-call (blank asr_model).
    assert captured["asr_model"] == ""
    assert captured["system_prompt"] == "DEFAULT PROMPT"


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
        # Return a tiny-but-nonempty buffer (too short to transcribe).
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

    # Start recording with the default profile.
    app._toggle_recording(DEFAULT_PROFILE_ID)
    assert rec.is_recording is True
    assert app._recording_profile_id == DEFAULT_PROFILE_ID

    # A different profile's hotkey fires: stop current, start new.
    app._toggle_recording("work-id")
    assert rec.is_recording is True  # recording again for the new profile
    assert app._recording_profile_id == "work-id"
    assert rec._stops == 1  # the first recording was stopped


def test_same_profile_hotkey_while_recording_stops(monkeypatch):
    app = App(headless=True)
    app._cfg = _cfg_with_profiles()
    rec = _FakeRecorder()
    app._rec = rec
    monkeypatch.setattr(app, "_check_mic_permission", lambda: True)
    monkeypatch.setattr(app, "_notify", lambda *a, **k: None)

    app._toggle_recording("work-id")
    assert rec.is_recording is True
    # Same profile fires again => stop.
    app._toggle_recording("work-id")
    assert rec.is_recording is False
    assert rec._stops == 1
