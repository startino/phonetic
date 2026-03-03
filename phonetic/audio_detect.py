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


def list_input_devices() -> list[dict]:
    """Return all available audio input devices.

    Returns a list of ``{"index": int, "name": str}`` dicts for every device
    whose ``max_input_channels > 0``.
    """
    devices = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            devices.append({"index": idx, "name": dev["name"]})
    return devices


def _try_open(device: Optional[int], label: str) -> bool:
    """Try opening a brief InputStream to validate the device works."""
    try:
        s = sd.InputStream(device=device, channels=1, dtype="float32")
        s.close()
        return True
    except Exception as e:
        print(f"[audio] {label} device {device} failed probe: {e}")
        return False


def detect_audio() -> tuple[int, int, Optional[int]]:
    """Return (sample_rate, channels, device_index) from the default input device.

    On Linux with PipeWire, tries in order:
      1. PulseAudio host API (pipewire-pulse)
      2. JACK host API (pipewire-jack) — matched by PipeWire default source name
    Falls back to the system default on all platforms.

    Every candidate is probe-opened before being returned so that transient
    device errors (e.g. Bluetooth not in capture mode) are caught early.
    """
    try:
        if sys.platform.startswith("linux"):
            pw_name = _pipewire_default_source()
            if pw_name:
                print(f"PipeWire default source: {pw_name}")

            apis = sd.query_hostapis()
            api_names = [a["name"] for a in apis]
            print(f"[audio] Available host APIs: {api_names}")

            # 1. Try PulseAudio
            for api in apis:
                if "pulse" not in api["name"].lower():
                    continue
                idx = api["default_input_device"]
                if idx >= 0 and _try_open(idx, "PulseAudio"):
                    dev = sd.query_devices(idx)
                    print(f"Audio device: {dev['name']} (PulseAudio)")
                    return int(dev["default_samplerate"]), 1, idx

            # 2. Try JACK — PipeWire exposes devices here when PulseAudio
            #    backend is unavailable (e.g. nix PortAudio without pulse)
            for api_idx, api in enumerate(apis):
                if "jack" not in api["name"].lower():
                    continue
                # If we know the PipeWire default source, find it by name
                if pw_name:
                    for dev_idx in api.get("devices", []):
                        dev = sd.query_devices(dev_idx)
                        if dev["max_input_channels"] <= 0:
                            continue
                        if pw_name.lower() in dev["name"].lower():
                            if _try_open(dev_idx, "JACK/PipeWire"):
                                print(f"Audio device: {dev['name']} (JACK/PipeWire)")
                                return int(dev["default_samplerate"]), 1, dev_idx
                # Otherwise use JACK's default input
                idx = api["default_input_device"]
                if idx >= 0 and _try_open(idx, "JACK"):
                    dev = sd.query_devices(idx)
                    print(f"Audio device: {dev['name']} (JACK)")
                    return int(dev["default_samplerate"]), 1, idx

        # Fallback: system default (CoreAudio on macOS, WASAPI on Windows,
        # ALSA on Linux when PulseAudio/JACK are unavailable)
        dev = sd.query_devices(kind="input")
        if _try_open(None, "fallback"):
            print(f"Audio device: {dev['name']} (fallback)")
            return int(dev["default_samplerate"]), 1, None
        raise RuntimeError("system default device failed to open")
    except Exception as e:
        raise RuntimeError(f"No audio input device found: {e}") from e
