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

    Queries PipeWire for the actual default source, then finds the matching
    JACK device in sounddevice. Falls back to JACK default, then ALSA default.
    """
    try:
        pw_name = _pipewire_default_source()

        for api in sd.query_hostapis():
            if "JACK" not in api["name"]:
                continue
            # Try to match PipeWire's default source by name
            if pw_name:
                for idx in api["devices"]:
                    dev = sd.query_devices(idx)
                    if dev["max_input_channels"] > 0 and pw_name in dev["name"]:
                        print(f"Audio device: {dev['name']} (PipeWire default)")
                        return int(dev["default_samplerate"]), 1, idx
            # Fall back to JACK's own default
            if api["default_input_device"] >= 0:
                dev = sd.query_devices(api["default_input_device"])
                print(f"Audio device: {dev['name']} (JACK default)")
                return int(dev["default_samplerate"]), 1, api["default_input_device"]

        dev = sd.query_devices(kind="input")
        print(f"Audio device: {dev['name']}")
        return int(dev["default_samplerate"]), 1, None
    except Exception as e:
        print(f"No audio input device found: {e}", file=sys.stderr)
        sys.exit(1)
