"""Regression tests for the long-recording silent-failure bug.

Two defects, fixed together:

* Bug A — a high-sample-rate recording (44.1/48 kHz) must be downsampled to
  16 kHz before send, unconditionally, so its payload never exceeds the
  provider's accept size. The old code gated on a 20 MB WAV-bytes threshold
  that sat above the real failing size, leaving a dead zone.
* Bug B — OpenRouter wraps upstream provider failures (e.g. an oversized-audio
  rejection surfaced as ``code: 429``) in an HTTP-200 body with an ``error``
  object and no ``choices``. The old code only checked the HTTP status, so
  these became empty transcriptions. They must now raise.
"""
import base64
import io

import numpy as np
import pytest
import soundfile as sf

import phonetic.transcribe as tr
from phonetic.config import Config
from phonetic.transcribe import transcribe


def _cfg(**overrides):
    base = dict(
        openrouter_api_key="sk-test",
        model="mistralai/voxtral-small-24b-2507",
        hotkey="<ctrl>+<alt>+r",
        sample_rate=44100,
        channels=1,
        device=None,
        notify=True,
        system_prompt="FORMAT PROMPT",
        asr_model="",
        format_model="mistralai/voxtral-small-24b-2507",
    )
    base.update(overrides)
    return Config(**base)


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    @property
    def is_success(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload

    @property
    def text(self):
        return str(self._payload)


class _RecordingClient:
    calls = []
    responses = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, json=None, data=None, files=None):
        type(self).calls.append(
            {"url": url, "headers": headers, "json": json, "data": data, "files": files}
        )
        return type(self).responses.pop(0)


@pytest.fixture
def recording_client(monkeypatch):
    _RecordingClient.calls = []
    _RecordingClient.responses = []
    monkeypatch.setattr(tr.httpx, "Client", _RecordingClient)
    return _RecordingClient


def _audio_44k(seconds=4.0):
    """A multi-second mono 44.1 kHz clip — the shape that triggered the bug."""
    n = int(44100 * seconds)
    t = np.linspace(0, seconds, n, endpoint=False, dtype=np.float32)
    return (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def _sent_b64_samplerate(call) -> int:
    b64 = call["json"]["messages"][0]["content"][1]["input_audio"]["data"]
    raw = base64.b64decode(b64)
    with sf.SoundFile(io.BytesIO(raw)) as f:
        return f.samplerate


# --- Bug A: always downsample the send payload to 16 kHz --------------------

def test_to_send_audio_downsamples_high_rate():
    audio = _audio_44k(1.0)
    out, rate = tr._to_send_audio(audio, 44100, "t")
    assert rate == 16000
    assert len(out) == 16000  # 1s at 16 kHz


def test_to_send_audio_collapses_stereo_to_mono():
    stereo = np.zeros((44100, 2), dtype=np.float32)
    out, rate = tr._to_send_audio(stereo, 44100, "t")
    assert rate == 16000
    assert out.ndim == 1


def test_to_send_audio_passes_through_16k():
    audio = np.zeros((16000,), dtype=np.float32)
    out, rate = tr._to_send_audio(audio, 16000, "t")
    assert rate == 16000
    assert out is audio  # untouched — preserves legacy payload exactly


def test_legacy_path_downsamples_44k_before_send(recording_client):
    recording_client.responses = [
        _FakeResponse({"choices": [{"message": {"content": "ok"}}]})
    ]
    cfg = _cfg(asr_model="")
    out = transcribe(cfg, _audio_44k(4.0), 44100)
    assert out == "ok"
    # The transmitted WAV must be 16 kHz, never the 44.1 kHz capture rate.
    assert _sent_b64_samplerate(recording_client.calls[0]) == 16000


# --- Bug B: a 200 body carrying an error must raise, not return "" ----------

_ERROR_BODY = {"error": {"message": "Provider returned error", "code": 429}}


def test_legacy_200_with_error_body_raises(recording_client):
    recording_client.responses = [_FakeResponse(_ERROR_BODY, status_code=200)]
    cfg = _cfg(asr_model="")
    with pytest.raises(RuntimeError) as exc:
        transcribe(cfg, _audio_44k(1.0), 44100)
    assert "429" in str(exc.value)


def test_legacy_200_no_choices_raises(recording_client):
    recording_client.responses = [_FakeResponse({"id": "x", "model": "m"}, status_code=200)]
    cfg = _cfg(asr_model="")
    with pytest.raises(RuntimeError):
        transcribe(cfg, _audio_44k(1.0), 44100)


def test_two_stage_chat_asr_200_error_raises(recording_client):
    recording_client.responses = [_FakeResponse(_ERROR_BODY, status_code=200)]
    cfg = _cfg(asr_model="some/chat-asr-model", format_model="openai/gpt-4o")
    with pytest.raises(RuntimeError) as exc:
        transcribe(cfg, _audio_44k(1.0), 44100)
    assert "429" in str(exc.value)


def test_two_stage_asr_only_200_error_raises(recording_client):
    recording_client.responses = [_FakeResponse(_ERROR_BODY, status_code=200)]
    cfg = _cfg(asr_model="nvidia/parakeet-tdt-0.6b-v3", format_model="openai/gpt-4o")
    with pytest.raises(RuntimeError) as exc:
        transcribe(cfg, _audio_44k(1.0), 44100)
    assert "429" in str(exc.value)


def test_format_stage_200_error_raises(recording_client):
    # ASR stage succeeds; the format stage gets the 200-with-error body.
    recording_client.responses = [
        _FakeResponse({"choices": [{"message": {"content": "raw transcript"}}]}),
        _FakeResponse(_ERROR_BODY, status_code=200),
    ]
    cfg = _cfg(asr_model="some/chat-asr-model", format_model="openai/gpt-4o")
    with pytest.raises(RuntimeError) as exc:
        transcribe(cfg, _audio_44k(1.0), 44100)
    assert "429" in str(exc.value)
