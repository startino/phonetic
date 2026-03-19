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
    """Send audio to OpenRouter for transcription+formatting via multimodal LLM."""
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
            "https://openrouter.ai/api/v1/chat/completions",
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
