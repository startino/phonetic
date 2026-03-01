import base64
import io

import httpx
import numpy as np
import soundfile as sf

from .config import Config


def audio_to_base64(audio: np.ndarray, sample_rate: int) -> str:
    """Encode audio numpy array as base64 WAV string."""
    buf = io.BytesIO()
    channels = audio.shape[1] if audio.ndim > 1 else 1
    with sf.SoundFile(buf, mode="w", samplerate=sample_rate, channels=channels,
                      subtype="PCM_16", format="WAV") as f:
        f.write(audio)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def transcribe(cfg: Config, audio: np.ndarray, sample_rate: int | None = None) -> str:
    """Send audio to OpenRouter for transcription+formatting via multimodal LLM."""
    if sample_rate is None:
        sample_rate = cfg.sample_rate
    duration = audio.shape[0] / sample_rate
    peak = float(np.max(np.abs(audio)))
    print(f"Audio: {duration:.1f}s, peak={peak:.4f}, rate={sample_rate}Hz")
    audio_b64 = audio_to_base64(audio, sample_rate)
    print(f"Base64 payload: {len(audio_b64)} chars")

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

    with httpx.Client(timeout=300) as client:
        resp = client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {cfg.openrouter_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if not resp.is_success:
            try:
                body = resp.json()
                msg = body.get("error", {}).get("message", "") or resp.text
            except Exception:
                msg = resp.text
            raise RuntimeError(f"OpenRouter {resp.status_code}: {msg}")
        data = resp.json()
        return (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
