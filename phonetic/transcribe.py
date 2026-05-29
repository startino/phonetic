import base64
import io
import json

import httpx
import numpy as np
import soundfile as sf

from .config import Config

# Write the last recorded WAV here so we can verify audio capture independently
_DEBUG_WAV = "/tmp/phonetic_debug.wav"

# Downsample to 16 kHz when the WAV payload would exceed this threshold (bytes).
# 16 kHz mono PCM-16 ≈ ~32 KB/s — a 7-minute recording is ~13 MB, well within API limits.
_MAX_WAV_BYTES = 20_000_000  # 20 MB
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

    # Save full-quality debug WAV before any downsampling
    try:
        buf = io.BytesIO()
        channels = audio.shape[1] if audio.ndim > 1 else 1
        with sf.SoundFile(buf, mode="w", samplerate=sample_rate, channels=channels,
                          subtype="PCM_16", format="WAV") as f:
            f.write(audio)
        debug_bytes = buf.getvalue()
        with open(_DEBUG_WAV, "wb") as df:
            df.write(debug_bytes)
        print(f"[transcribe] Debug WAV saved to {_DEBUG_WAV} ({len(debug_bytes)} bytes)")
    except Exception as e:
        print(f"[transcribe] Could not save debug WAV: {e}")
        debug_bytes = None

    # Downsample long recordings to keep the API payload manageable
    est_wav_size = debug_bytes and len(debug_bytes) or (audio.shape[0] * 2 * channels + 44)
    if sample_rate > _DOWNSAMPLE_RATE and est_wav_size > _MAX_WAV_BYTES:
        print(f"[transcribe] WAV too large ({est_wav_size} bytes), "
              f"downsampling {sample_rate}Hz -> {_DOWNSAMPLE_RATE}Hz")
        if audio.ndim > 1:
            audio = audio[:, 0]
        audio = _downsample(audio, sample_rate, _DOWNSAMPLE_RATE)
        sample_rate = _DOWNSAMPLE_RATE
        print(f"[transcribe] After downsample: shape={audio.shape}, rate={sample_rate}Hz")

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
        print(f"[transcribe] Response status: {resp.status_code}")
        if not resp.is_success:
            try:
                body = resp.json()
                msg = body.get("error", {}).get("message", "") or resp.text
            except Exception:
                msg = resp.text
            raise RuntimeError(f"OpenRouter {resp.status_code}: {msg}")
        data = resp.json()
        # Log the full response (model used, usage, etc.)
        debug_resp = {k: v for k, v in data.items() if k != "choices"}
        print(f"[transcribe] Response meta: {json.dumps(debug_resp)}")
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        print(f"[transcribe] Transcription ({len(text)} chars): {text[:200]!r}")
        return text


def _prepare_audio(audio: np.ndarray, sample_rate: int | None) -> tuple[np.ndarray, int]:
    """Save debug WAV and downsample long recordings. Shared by the ASR stage."""
    if sample_rate is None:
        sample_rate = 0  # caller guarantees a real rate; guard for safety
    duration = audio.shape[0] / sample_rate if sample_rate else 0.0
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    print(f"[asr] Audio: {duration:.1f}s, peak={peak:.4f}, rate={sample_rate}Hz, "
          f"shape={audio.shape}, dtype={audio.dtype}")

    # Save full-quality debug WAV before any downsampling
    debug_bytes = None
    try:
        buf = io.BytesIO()
        channels = audio.shape[1] if audio.ndim > 1 else 1
        with sf.SoundFile(buf, mode="w", samplerate=sample_rate, channels=channels,
                          subtype="PCM_16", format="WAV") as f:
            f.write(audio)
        debug_bytes = buf.getvalue()
        with open(_DEBUG_WAV, "wb") as df:
            df.write(debug_bytes)
        print(f"[asr] Debug WAV saved to {_DEBUG_WAV} ({len(debug_bytes)} bytes)")
    except Exception as e:
        print(f"[asr] Could not save debug WAV: {e}")
        channels = audio.shape[1] if audio.ndim > 1 else 1

    est_wav_size = debug_bytes and len(debug_bytes) or (audio.shape[0] * 2 * channels + 44)
    if sample_rate > _DOWNSAMPLE_RATE and est_wav_size > _MAX_WAV_BYTES:
        print(f"[asr] WAV too large ({est_wav_size} bytes), "
              f"downsampling {sample_rate}Hz -> {_DOWNSAMPLE_RATE}Hz")
        if audio.ndim > 1:
            audio = audio[:, 0]
        audio = _downsample(audio, sample_rate, _DOWNSAMPLE_RATE)
        sample_rate = _DOWNSAMPLE_RATE
        print(f"[asr] After downsample: shape={audio.shape}, rate={sample_rate}Hz")
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
            print(f"[asr] Response status: {resp.status_code}")
            if not resp.is_success:
                try:
                    body = resp.json()
                    msg = body.get("error", {}).get("message", "") or resp.text
                except Exception:
                    msg = resp.text
                raise RuntimeError(f"OpenRouter {resp.status_code}: {msg}")
            data = resp.json()
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
        print(f"[asr] Response status: {resp.status_code}")
        if not resp.is_success:
            try:
                body = resp.json()
                msg = body.get("error", {}).get("message", "") or resp.text
            except Exception:
                msg = resp.text
            raise RuntimeError(f"OpenRouter {resp.status_code}: {msg}")
        data = resp.json()
        debug_resp = {k: v for k, v in data.items() if k != "choices"}
        print(f"[asr] Response meta: {json.dumps(debug_resp)}")
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
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
        print(f"[format] Response status: {resp.status_code}")
        if not resp.is_success:
            try:
                body = resp.json()
                msg = body.get("error", {}).get("message", "") or resp.text
            except Exception:
                msg = resp.text
            raise RuntimeError(f"OpenRouter {resp.status_code}: {msg}")
        data = resp.json()
        debug_resp = {k: v for k, v in data.items() if k != "choices"}
        print(f"[format] Response meta: {json.dumps(debug_resp)}")
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        print(f"[format] Formatted ({len(text)} chars): {text[:200]!r}")
        return text
