import subprocess
import sys
from typing import Optional

import sounddevice as sd


def _pipewire_default_source() -> Optional[str]:
    """Query PipeWire for the default source's node.description."""
    try:
        r = subprocess.run(
            ["wpctl", "inspect", "@DEFAULT_SOURCE@"],
            capture_output=True, text=True, timeout=5,
        )
        for line in r.stdout.splitlines():
            if "node.description" in line:
                return line.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return None


def detect_audio() -> tuple[int, int, Optional[int]]:
    """Return (sample_rate, channels, device_index) from the default input device.

    On Linux, prefers PulseAudio (routes through PipeWire reliably via
    pipewire-pulse). Falls back to the system default on all platforms.
    """
    try:
        # On Linux, prefer PulseAudio — it routes through PipeWire reliably
        if sys.platform.startswith("linux"):
            pw_name = _pipewire_default_source()
            if pw_name:
                print(f"PipeWire default source: {pw_name}")

            for api in sd.query_hostapis():
                if "pulse" not in api["name"].lower():
                    continue
                idx = api["default_input_device"]
                if idx >= 0:
                    dev = sd.query_devices(idx)
                    print(f"Audio device: {dev['name']} (PulseAudio)")
                    return int(dev["default_samplerate"]), 1, idx

        # Fallback: system default (CoreAudio on macOS, WASAPI on Windows,
        # ALSA on Linux when PulseAudio is unavailable)
        dev = sd.query_devices(kind="input")
        print(f"Audio device: {dev['name']}")
        return int(dev["default_samplerate"]), 1, None
    except Exception as e:
        raise RuntimeError(f"No audio input device found: {e}") from e
