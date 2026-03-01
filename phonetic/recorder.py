import queue
import sys
from typing import Optional

import numpy as np
import sounddevice as sd


class Recorder:
    def __init__(self, sample_rate: int, channels: int, device: Optional[int] = None) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device
        self._q: "queue.Queue[np.ndarray]" = queue.Queue()
        self._stream: Optional[sd.InputStream] = None
        self._frames: list[np.ndarray] = []
        self.is_recording = False

    def _callback(self, indata, frames, time_info, status):
        if status:
            print(status, file=sys.stderr)
        self._q.put(indata.copy())

    def start(self) -> None:
        if self.is_recording:
            return
        self._frames.clear()
        self._q = queue.Queue()
        self._stream = sd.InputStream(
            device=self.device,
            channels=self.channels,
            dtype="float32",
            callback=self._callback,
        )
        # Use the stream's actual sample rate (auto-detected from device)
        self.sample_rate = int(self._stream.samplerate)
        self._stream.start()
        self.is_recording = True

    def stop(self) -> np.ndarray:
        if not self.is_recording:
            return np.empty((0, self.channels), dtype=np.float32)
        assert self._stream is not None
        self._stream.stop()
        self._stream.close()
        self._stream = None
        self.is_recording = False
        while not self._q.empty():
            try:
                self._frames.append(self._q.get_nowait())
            except queue.Empty:
                break
        if not self._frames:
            return np.empty((0, self.channels), dtype=np.float32)
        audio = np.concatenate(self._frames, axis=0)
        audio = np.clip(audio, -1.0, 1.0).astype(np.float32)
        # Diagnostic: audio buffer stats
        peak = float(np.max(np.abs(audio)))
        rms = float(np.sqrt(np.mean(audio ** 2)))
        print(f"[recorder] frames={len(self._frames)}, shape={audio.shape}, "
              f"dtype={audio.dtype}, peak={peak:.4f}, rms={rms:.6f}, "
              f"rate={self.sample_rate}Hz")
        return audio
