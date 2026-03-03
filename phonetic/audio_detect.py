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


def _find_alsa_pipewire_device() -> Optional[int]:
    """Find the ALSA device named 'pipewire' or 'default'.

    On PipeWire systems, these ALSA virtual devices route through PipeWire's
    ALSA plugin to the correct default source.  This is more reliable than
    JACK, which exposes monitor/loopback ports for every device (including
    Bluetooth output-only sinks) as fake input devices.
    """
    apis = sd.query_hostapis()
    for api in apis:
        if "alsa" not in api["name"].lower():
            continue
        for dev_idx in api.get("devices", []):
            dev = sd.query_devices(dev_idx)
            if dev["max_input_channels"] <= 0:
                continue
            name = dev["name"].lower()
            if name == "pipewire":
                return dev_idx
        # No 'pipewire' device; try 'default'
        idx = api["default_input_device"]
        if idx >= 0:
            return idx
    return None


def detect_audio() -> tuple[int, int, Optional[int]]:
    """Return (sample_rate, channels, device_index) from the default input device.

    On Linux, tries in order:
      1. PulseAudio host API (pipewire-pulse)
      2. ALSA 'pipewire' or 'default' device (PipeWire ALSA plugin — most
         reliable when PortAudio lacks a PulseAudio backend, e.g. nixpkgs)
      3. System default (``device=None``)
    """
    try:
        if sys.platform.startswith("linux"):
            apis = sd.query_hostapis()
            api_names = [a["name"] for a in apis]
            print(f"[audio] Available host APIs: {api_names}")

            # 1. Try PulseAudio
            for api in apis:
                if "pulse" not in api["name"].lower():
                    continue
                idx = api["default_input_device"]
                if idx >= 0:
                    dev = sd.query_devices(idx)
                    print(f"Audio device: {dev['name']} (PulseAudio)")
                    return int(dev["default_samplerate"]), 1, idx

            # 2. Try ALSA pipewire/default — routes through PipeWire on
            #    modern Linux, avoids JACK's unreliable loopback ports
            alsa_idx = _find_alsa_pipewire_device()
            if alsa_idx is not None:
                dev = sd.query_devices(alsa_idx)
                print(f"Audio device: {dev['name']} (ALSA/PipeWire)")
                return int(dev["default_samplerate"]), 1, alsa_idx

        # Fallback: system default (CoreAudio on macOS, WASAPI on Windows,
        # ALSA on Linux when PulseAudio/JACK are unavailable)
        dev = sd.query_devices(kind="input")
        print(f"Audio device: {dev['name']} (fallback)")
        return int(dev["default_samplerate"]), 1, None
    except Exception as e:
        raise RuntimeError(f"No audio input device found: {e}") from e
