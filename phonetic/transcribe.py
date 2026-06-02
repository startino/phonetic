import base64
import io
import json

import httpx
import numpy as np
import soundfile as sf

from .config import Config

# Write the last recorded WAV here so we can verify audio capture independently
_DEBUG_WAV = "/tmp/phonetic_debug.wav"

# Target sample rate for everything we send to the API. Voxtral and the other
# speech-to-text models OpenRouter serves are trained at 16 kHz; native-rate
# capture (44.1/48 kHz) buys ASR nothing and inflates the payload ~2.75x. We
# ALWAYS downsample the send payload to 16 kHz mono — there is no size
# threshold to get wrong. A prior bug used a 20 MB WAV-bytes threshold that sat
# ABOVE the provider's real accept size, so a ~3.5-min 44.1 kHz recording
# (18.2 MB WAV / 24.3 MB base64) slipped through unmodified and was rejected
# upstream with an HTTP-200-wrapped 429. See docs/fixes/0001-*.
_DOWNSAMPLE_RATE = 16_000

# OpenRouter base URLs for the two endpoint families.
_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
_AUDIO_URL = "https://openrouter.ai/api/v1/audio/transcriptions"

# Minimal ASR-only instruction for chat-style ASR models in the two-stage path.
_ASR_PROMPT = "Transcribe the audio exactly as spoken, no formatting, no commentary."

# Substrings (case-insensitive) that mark a model as served by OpenRouter's
# /audio/transcriptions endpoint rather than /chat/completions. Extend freely.
_ASR_ONLY_SUBSTRINGS: tuple[str, ...] = ("parakeet",)


def _is_asr_only_model(model_id: str) -> bool:
    """True if model_id is served by OpenRouter's transcription endpoint."""
    lowered = (model_id or "").lower()
    return any(sub in lowered for sub in _ASR_ONLY_SUBSTRINGS)


def _downsample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Downsample audio via linear interpolation (no scipy dependency)."""
    old_len = len(audio)
    new_len = int(old_len * dst_rate / src_rate)
    old_indices = np.linspace(0, old_len - 1, new_len)
    lower = np.floor(old_indices).astype(int)
    upper = np.minimum(lower + 1, old_len - 1)
    frac = old_indices - lower
    if audio.ndim > 1:
        frac = frac[:, np.newaxis]
    return (audio[lower] * (1 - frac) + audio[upper] * frac).astype(audio.dtype)


def _save_debug_wav(audio: np.ndarray, sample_rate: int, tag: str) -> bytes | None:
    """Write the full-quality recording to _DEBUG_WAV before any downsampling.

    Returns the WAV bytes, or None if the write failed. Best-effort: a failure
    here never blocks transcription.
    """
    try:
        buf = io.BytesIO()
        channels = audio.shape[1] if audio.ndim > 1 else 1
        with sf.SoundFile(buf, mode="w", samplerate=sample_rate, channels=channels,
                          subtype="PCM_16", format="WAV") as f:
            f.write(audio)
        debug_bytes = buf.getvalue()
        with open(_DEBUG_WAV, "wb") as df:
            df.write(debug_bytes)
        print(f"[{tag}] Debug WAV saved to {_DEBUG_WAV} ({len(debug_bytes)} bytes)")
        return debug_bytes
    except Exception as e:
        print(f"[{tag}] Could not save debug WAV: {e}")
        return None


def _to_send_audio(audio: np.ndarray, sample_rate: int, tag: str) -> tuple[np.ndarray, int]:
    """Render the audio that will actually be transmitted: <=16 kHz mono.

    Always downsamples when the capture rate exceeds 16 kHz. This is the single
    source of truth for send-payload sizing — there is no byte threshold. A
    recording captured at 44.1/48 kHz is collapsed to 16 kHz mono so its
    encoded payload stays well under the provider's accept size regardless of
    duration. Audio already at or below 16 kHz is passed through untouched.
    """
    if sample_rate > _DOWNSAMPLE_RATE:
        if audio.ndim > 1:
            audio = audio[:, 0]
        print(f"[{tag}] Downsampling {sample_rate}Hz -> {_DOWNSAMPLE_RATE}Hz for send")
        audio = _downsample(audio, sample_rate, _DOWNSAMPLE_RATE)
        sample_rate = _DOWNSAMPLE_RATE
        print(f"[{tag}] After downsample: shape={audio.shape}, rate={sample_rate}Hz")
    return audio, sample_rate


def _parse_response(resp, tag: str) -> dict:
    """Validate an OpenRouter response and return its parsed JSON, or raise.

    Two failure modes are treated identically as hard errors:

    1. A non-2xx HTTP status (the usual case).
    2. An HTTP-200 body that carries an ``{"error": {...}}`` object. OpenRouter
       wraps upstream provider failures — an oversized-audio rejection surfaces
       as ``code: 429``, a content-policy block, a model-down, a quota hit — in
       a 200 response with no ``choices``. The previous code only checked the
       HTTP status, so these silently became empty transcriptions. They must
       surface as errors so the caller's critical-notification path fires.
    """
    print(f"[{tag}] Response status: {resp.status_code}")
    if not resp.is_success:
        try:
            body = resp.json()
            msg = body.get("error", {}).get("message", "") or resp.text
        except Exception:
            msg = resp.text
        raise RuntimeError(f"OpenRouter {resp.status_code}: {msg}")
    data = resp.json()
    meta = {k: v for k, v in data.items() if k != "choices"}
    print(f"[{tag}] Response meta: {json.dumps(meta)}")
    err = data.get("error")
    if err:
        code = err.get("code", resp.status_code) if isinstance(err, dict) else resp.status_code
        msg = (err.get("message", "") if isinstance(err, dict) else "") or str(err)
        raise RuntimeError(f"OpenRouter {code}: {msg}")
    return data


def _chat_text(data: dict, tag: str) -> str:
    """Extract assistant text from a validated chat/completions response.

    ``data`` must already have passed :func:`_parse_response` (no error body).
    A missing/empty ``choices`` array on an otherwise-OK response is malformed
    and raised rather than laundered into an empty transcription.
    """
    choices = data.get("choices")
    if not choices:
        meta = {k: v for k, v in data.items() if k != "choices"}
        raise RuntimeError(f"OpenRouter returned no choices: {json.dumps(meta)}")
    return (choices[0] or {}).get("message", {}).get("content", "") or ""


def audio_to_base64(audio: np.ndarray, sample_rate: int) -> str:
    """Encode audio numpy array as base64 WAV string."""
    buf = io.BytesIO()
    channels = audio.shape[1] if audio.ndim > 1 else 1
    with sf.SoundFile(buf, mode="w", samplerate=sample_rate, channels=channels,
                      subtype="PCM_16", format="WAV") as f:
        f.write(audio)
    wav_bytes = buf.getvalue()
    print(f"[transcribe] WAV size: {len(wav_bytes)} bytes, "
          f"channels={channels}, rate={sample_rate}Hz")
    return base64.b64encode(wav_bytes).decode("ascii")


def transcribe(cfg: Config, audio: np.ndarray, sample_rate: int | None = None) -> str:
    """Send audio to OpenRouter for transcription.

    When cfg.asr_model is blank, uses the legacy single multimodal call
    (unchanged behavior). When set, runs the two-stage pipeline: ASR then
    formatting via cfg.format_model.
    """
    if cfg.asr_model:
        print(f"[transcribe] Two-stage pipeline: asr_model={cfg.asr_model!r} "
              f"format_model={cfg.format_model!r}")
        raw = _run_asr(cfg, audio, sample_rate)
        return _run_format(cfg, raw)

    print("[transcribe] Legacy single-call pipeline (no asr_model)")
    if sample_rate is None:
        sample_rate = cfg.sample_rate
    duration = audio.shape[0] / sample_rate
    peak = float(np.max(np.abs(audio)))
    print(f"[transcribe] Audio: {duration:.1f}s, peak={peak:.4f}, rate={sample_rate}Hz, "
          f"shape={audio.shape}, dtype={audio.dtype}")

    # Save full-quality debug WAV before any downsampling, then render the send
    # payload at 16 kHz mono (always — see _to_send_audio).
    _save_debug_wav(audio, sample_rate, "transcribe")
    audio, sample_rate = _to_send_audio(audio, sample_rate, "transcribe")

    audio_b64 = audio_to_base64(audio, sample_rate)
    print(f"[transcribe] Base64 payload: {len(audio_b64)} chars")

    payload = {
        "model": cfg.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": cfg.system_prompt,
                    },
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": audio_b64,
                            "format": "wav",
                        },
                    },
                ],
            },
        ],
    }

    # Log the payload structure (without the huge base64 blob)
    debug_payload = json.loads(json.dumps(payload))
    for msg in debug_payload.get("messages", []):
        for part in msg.get("content", []):
            if part.get("type") == "input_audio":
                data_len = len(part["input_audio"]["data"])
                part["input_audio"]["data"] = f"<{data_len} chars>"
    print(f"[transcribe] Request payload: {json.dumps(debug_payload, indent=2)}")

    with httpx.Client(timeout=300) as client:
        resp = client.post(
            _CHAT_URL,
            headers={
                "Authorization": f"Bearer {cfg.openrouter_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        data = _parse_response(resp, "transcribe")
        text = _chat_text(data, "transcribe")
        print(f"[transcribe] Transcription ({len(text)} chars): {text[:200]!r}")
        return text


def _prepare_audio(audio: np.ndarray, sample_rate: int | None) -> tuple[np.ndarray, int]:
    """Save debug WAV and render the send payload at 16 kHz. Shared by the ASR stage."""
    if sample_rate is None:
        sample_rate = 0  # caller guarantees a real rate; guard for safety
    duration = audio.shape[0] / sample_rate if sample_rate else 0.0
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    print(f"[asr] Audio: {duration:.1f}s, peak={peak:.4f}, rate={sample_rate}Hz, "
          f"shape={audio.shape}, dtype={audio.dtype}")

    _save_debug_wav(audio, sample_rate, "asr")
    audio, sample_rate = _to_send_audio(audio, sample_rate, "asr")
    return audio, sample_rate


def _run_asr(cfg: Config, audio: np.ndarray, sample_rate: int | None = None) -> str:
    """Stage 1: pure ASR. Returns the raw, unformatted transcript.

    Guard: if cfg.asr_model is empty, returns "" (the caller decides the path
    before calling, so this should not happen on the two-stage route).
    """
    if not cfg.asr_model:
        print("[asr] asr_model is empty — returning '' (legacy path expected)")
        return ""

    if sample_rate is None:
        sample_rate = cfg.sample_rate
    audio, sample_rate = _prepare_audio(audio, sample_rate)

    if _is_asr_only_model(cfg.asr_model):
        print(f"[asr] model={cfg.asr_model!r} is ASR-only → endpoint {_AUDIO_URL}")
        buf = io.BytesIO()
        channels = audio.shape[1] if audio.ndim > 1 else 1
        with sf.SoundFile(buf, mode="w", samplerate=sample_rate, channels=channels,
                          subtype="PCM_16", format="WAV") as f:
            f.write(audio)
        wav_bytes = buf.getvalue()
        print(f"[asr] multipart WAV: {len(wav_bytes)} bytes, model={cfg.asr_model!r}")
        with httpx.Client(timeout=300) as client:
            resp = client.post(
                _AUDIO_URL,
                headers={"Authorization": f"Bearer {cfg.openrouter_api_key}"},
                data={"model": cfg.asr_model},
                files={"file": ("audio.wav", wav_bytes, "audio/wav")},
            )
            data = _parse_response(resp, "asr")
            text = data.get("text", "") or ""
            print(f"[asr] Transcript ({len(text)} chars): {text[:200]!r}")
            return text

    # Chat-style ASR model: minimal ASR-only prompt + input_audio, no formatting.
    print(f"[asr] model={cfg.asr_model!r} is chat-style → endpoint {_CHAT_URL}")
    audio_b64 = audio_to_base64(audio, sample_rate)
    print(f"[asr] Base64 payload: {len(audio_b64)} chars")
    payload = {
        "model": cfg.asr_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _ASR_PROMPT},
                    {
                        "type": "input_audio",
                        "input_audio": {"data": audio_b64, "format": "wav"},
                    },
                ],
            },
        ],
    }
    with httpx.Client(timeout=300) as client:
        resp = client.post(
            _CHAT_URL,
            headers={
                "Authorization": f"Bearer {cfg.openrouter_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        data = _parse_response(resp, "asr")
        text = _chat_text(data, "asr")
        print(f"[asr] Transcript ({len(text)} chars): {text[:200]!r}")
        return text


def _run_format(cfg: Config, raw_transcript: str) -> str:
    """Stage 2: format the raw transcript via cfg.format_model (text-only)."""
    print(f"[format] model={cfg.format_model!r} input_len={len(raw_transcript)}")
    payload = {
        "model": cfg.format_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": cfg.system_prompt},
                    {"type": "text", "text": raw_transcript},
                ],
            },
        ],
    }
    with httpx.Client(timeout=300) as client:
        resp = client.post(
            _CHAT_URL,
            headers={
                "Authorization": f"Bearer {cfg.openrouter_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        data = _parse_response(resp, "format")
        text = _chat_text(data, "format")
        print(f"[format] Formatted ({len(text)} chars): {text[:200]!r}")
        return text
