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
        self._cb_logged = False

    def _callback(self, indata, frames, time_info, status):
        if status:
            print(status, file=sys.stderr)
        self._q.put(indata.copy())
        if not self._cb_logged:
            print(f"[recorder] first callback: frames={frames}, shape={indata.shape}, "
                  f"qsize={self._q.qsize()}")
            self._cb_logged = True

    def start(self) -> None:
        if self.is_recording:
            return
        self._frames.clear()
        self._q = queue.Queue()
        self._cb_logged = False
        try:
            self._stream = sd.InputStream(
                device=self.device,
                channels=self.channels,
                dtype="float32",
                callback=self._callback,
            )
            self._stream.start()
        except Exception as e:
            if self.device is not None:
                print(f"[recorder] device {self.device} failed: {e}, "
                      f"retrying with system default", file=sys.stderr)
                self.device = None
                self._stream = sd.InputStream(
                    channels=self.channels,
                    dtype="float32",
                    callback=self._callback,
                )
                self._stream.start()
            else:
                raise
        # Use the stream's actual sample rate (auto-detected from device)
        self.sample_rate = int(self._stream.samplerate)
        self.is_recording = True

    def peek_level(self) -> float:
        """Check peak amplitude of audio captured so far without stopping.

        Drains the internal queue into the frame buffer (same as stop() does)
        so frames are not lost.  Returns 0.0 if no frames yet.
        """
        if not self.is_recording:
            return 0.0
        while not self._q.empty():
            try:
                self._frames.append(self._q.get_nowait())
            except queue.Empty:
                break
        if not self._frames:
            print(f"[recorder] peek_level: no frames yet (qsize={self._q.qsize()}, cb_fired={self._cb_logged})")
            return 0.0
        audio = np.concatenate(self._frames, axis=0)
        peak = float(np.max(np.abs(audio)))
        print(f"[recorder] peek_level: frames={len(self._frames)}, samples={audio.shape[0]}, peak={peak:.6f}")
        return peak

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
