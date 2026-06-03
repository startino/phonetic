"""Wave 1 transcribe tests: ASR-only detection + legacy vs two-stage routing."""
import numpy as np
import pytest

import phonetic.transcribe as tr
from phonetic.config import Config
from phonetic.transcribe import _is_asr_only_model, transcribe


def _cfg(**overrides):
    base = dict(
        openrouter_api_key="sk-test",
        model="google/gemini-3-flash-preview",
        sample_rate=16000,
        channels=1,
        device=None,
        notify=True,
        system_prompt="FORMAT PROMPT",
        asr_model="",
        format_model="google/gemini-3-flash-preview",
    )
    base.update(overrides)
    return Config(**base)


def _audio():
    # ~0.5s of quiet tone at 16kHz mono float32.
    n = 8000
    t = np.linspace(0, 0.5, n, endpoint=False, dtype=np.float32)
    return (0.01 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


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
    """Stand-in for httpx.Client that records posts and returns queued responses."""

    calls = []  # list of dicts captured across all instances
    responses = []  # FIFO queue of _FakeResponse to return

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


# --- _is_asr_only_model ----------------------------------------------------

@pytest.mark.parametrize("model_id,expected", [
    ("nvidia/parakeet-tdt-0.6b-v3", True),
    ("NVIDIA/Parakeet-TDT", True),
    ("openai/gpt-4o", False),
    ("google/gemini-3-flash-preview", False),
    ("", False),
])
def test_is_asr_only_model(model_id, expected):
    assert _is_asr_only_model(model_id) is expected


# --- legacy single-call path (backward compat) -----------------------------

def test_legacy_path_payload_unchanged(recording_client):
    recording_client.responses = [
        _FakeResponse({"choices": [{"message": {"content": "legacy out"}}]})
    ]
    cfg = _cfg(asr_model="")  # legacy
    out = transcribe(cfg, _audio(), 16000)
    assert out == "legacy out"

    assert len(recording_client.calls) == 1
    call = recording_client.calls[0]
    assert call["url"] == "https://openrouter.ai/api/v1/chat/completions"
    payload = call["json"]
    assert payload["model"] == "google/gemini-3-flash-preview"
    content = payload["messages"][0]["content"]
    # text == system_prompt, then input_audio. Exactly the legacy structure.
    assert content[0] == {"type": "text", "text": "FORMAT PROMPT"}
    assert content[1]["type"] == "input_audio"
    assert content[1]["input_audio"]["format"] == "wav"
    assert isinstance(content[1]["input_audio"]["data"], str)
    # Legacy path must NOT hit the audio/transcriptions endpoint.
    assert call["files"] is None


# --- two-stage: ASR-only model (multipart) + format ------------------------

def test_two_stage_asr_only_model(recording_client):
    recording_client.responses = [
        _FakeResponse({"text": "raw parakeet transcript"}),
        _FakeResponse({"choices": [{"message": {"content": "formatted result"}}]}),
    ]
    cfg = _cfg(
        asr_model="nvidia/parakeet-tdt-0.6b-v3",
        format_model="openai/gpt-4o",
    )
    out = transcribe(cfg, _audio(), 16000)
    assert out == "formatted result"
    assert len(recording_client.calls) == 2

    asr_call, fmt_call = recording_client.calls
    # Stage 1: multipart to /audio/transcriptions, model field, file field, no prompt.
    assert asr_call["url"] == "https://openrouter.ai/api/v1/audio/transcriptions"
    assert asr_call["data"] == {"model": "nvidia/parakeet-tdt-0.6b-v3"}
    assert "file" in asr_call["files"]
    assert asr_call["json"] is None

    # Stage 2: chat/completions with format_model, system_prompt + raw transcript.
    assert fmt_call["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert fmt_call["json"]["model"] == "openai/gpt-4o"
    content = fmt_call["json"]["messages"][0]["content"]
    assert content[0]["text"] == "FORMAT PROMPT"
    assert content[1]["text"] == "raw parakeet transcript"
    # No audio in the formatting call.
    assert all(part["type"] == "text" for part in content)


# --- two-stage: chat-style ASR model ---------------------------------------

def test_two_stage_chat_asr_model(recording_client):
    recording_client.responses = [
        _FakeResponse({"choices": [{"message": {"content": "raw chat transcript"}}]}),
        _FakeResponse({"choices": [{"message": {"content": "formatted"}}]}),
    ]
    cfg = _cfg(
        asr_model="some/chat-asr-model",
        format_model="openai/gpt-4o",
    )
    out = transcribe(cfg, _audio(), 16000)
    assert out == "formatted"
    asr_call, fmt_call = recording_client.calls
    # Chat-style ASR uses chat/completions with the minimal ASR-only prompt.
    assert asr_call["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert asr_call["json"]["model"] == "some/chat-asr-model"
    asr_content = asr_call["json"]["messages"][0]["content"]
    assert asr_content[0]["text"] == tr._ASR_PROMPT
    assert asr_content[1]["type"] == "input_audio"
