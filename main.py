import os
import sys
import time
import queue
import base64
import io
import signal
import subprocess
import atexit
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf
import httpx
from dotenv import load_dotenv

if sys.platform.startswith("linux"):
    from Xlib import X, XK, display
else:
    from pynput import keyboard as kb_nix


DEFAULT_SYSTEM_PROMPT = """\
Transcribe the attached audio file. Please format nicely. Be accurate to what was said but make it comprehensible.
If the audio for some reason is incomprehensible, instead of responding to this request, just try your best.
Never output anything other than the transcription.
Especially nothing like a correction or telling the user hey this doesn't make sense just output your best attempt.
Please format it nicely, you know, paragraphs, proper punctuation, proper capitalization. Remove some of the filler if the user says um a lot. Remove corrections, so if the user corrects themselves, then you should remove the first part they said and make it one coherent sentence, as if they said the correct thing just all along. But don't change the wording that the user uses, so only make sure that it's like capitalization, punctuation, new paragraphs, the such, but don't change their words.\
"""

MIN_DURATION_SECS = 0.5
WARN_DURATION_SECS = 300


@dataclass
class Config:
    openrouter_api_key: str
    model: str
    hotkey: str
    sample_rate: int
    channels: int
    device: Optional[int]
    notify: bool
    system_prompt: str


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


def _detect_audio() -> tuple[int, int, Optional[int]]:
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


def load_config() -> Config:
    load_dotenv()

    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        print("OPENROUTER_API_KEY is required", file=sys.stderr)
        sys.exit(1)

    sample_rate, channels, device = _detect_audio()

    return Config(
        openrouter_api_key=api_key,
        model=os.getenv("MODEL", "google/gemini-3-flash-preview").strip(),
        hotkey=os.getenv("HOTKEY", "<ctrl>+<alt>+r").strip(),
        sample_rate=sample_rate,
        channels=channels,
        device=device,
        notify=os.getenv("NOTIFY", "1").strip() not in {"0", "false", "no"},
        system_prompt=os.getenv("SYSTEM_PROMPT", "").strip() or DEFAULT_SYSTEM_PROMPT,
    )


_notify_id: Optional[str] = None


def notify(cfg: Config, body: str, urgency: str = "normal", persist: bool = False, replace: bool = False) -> None:
    """Send a desktop notification if enabled and on Linux.

    If persist=True, the notification won't auto-dismiss and its ID is stored.
    If replace=True, replaces the previously persisted notification.
    """
    global _notify_id
    if not cfg.notify or not sys.platform.startswith("linux"):
        return
    try:
        cmd = ["notify-send", "--urgency", urgency, "--print-id", "Phonetic", body]
        if persist:
            cmd.extend(["-t", "0"])
        if replace and _notify_id:
            cmd.extend(["--replace-id", _notify_id])
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
        nid = result.stdout.strip()
        if persist and nid:
            _notify_id = nid
        elif replace:
            _notify_id = None
    except Exception:
        pass


def _is_wayland() -> bool:
    """Detect Wayland session even inside systemd services."""
    if (os.getenv("XDG_SESSION_TYPE") or "").lower() == "wayland":
        return True
    if os.getenv("WAYLAND_DISPLAY"):
        return True
    runtime = os.getenv("XDG_RUNTIME_DIR")
    if runtime:
        for name in ("wayland-0", "wayland-1"):
            if os.path.exists(os.path.join(runtime, name)):
                return True
    return False


def copy_to_clipboard(text: str) -> None:
    """Copy text to system clipboard using native tools."""
    if sys.platform.startswith("linux"):
        if _is_wayland():
            subprocess.run(
                ["wl-copy"],
                input=text.encode("utf-8"),
                check=True,
                timeout=5,
            )
        else:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text.encode("utf-8"),
                check=True,
                timeout=5,
            )
    else:
        import pyperclip
        pyperclip.copy(text)


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
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            callback=self._callback,
        )
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
        return audio


def audio_to_base64(audio: np.ndarray, sample_rate: int) -> str:
    """Encode audio numpy array as base64 WAV string."""
    buf = io.BytesIO()
    channels = audio.shape[1] if audio.ndim > 1 else 1
    with sf.SoundFile(buf, mode="w", samplerate=sample_rate, channels=channels,
                      subtype="PCM_16", format="WAV") as f:
        f.write(audio)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def transcribe(cfg: Config, audio: np.ndarray) -> str:
    """Send audio to OpenRouter for transcription+formatting via multimodal LLM."""
    duration = audio.shape[0] / cfg.sample_rate
    peak = float(np.max(np.abs(audio)))
    print(f"Audio: {duration:.1f}s, peak={peak:.4f}, rate={cfg.sample_rate}Hz")
    audio_b64 = audio_to_base64(audio, cfg.sample_rate)
    print(f"Base64 payload: {len(audio_b64)} chars")

    payload = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": cfg.system_prompt},
            {
                "role": "user",
                "content": [
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


def main() -> None:
    cfg = load_config()
    rec = Recorder(sample_rate=cfg.sample_rate, channels=cfg.channels, device=cfg.device)
    processing = False

    def toggle_recording():
        nonlocal processing
        if processing:
            return
        if not rec.is_recording:
            print(f"Recording... Press {cfg.hotkey} to stop.")
            try:
                rec.start()
            except Exception as e:
                print(f"Audio input error: {e}", file=sys.stderr)
                notify(cfg, f"Audio input error: {e}", "critical")
                return
            notify(cfg, "Recording started", "low", persist=True)
        else:
            print("Stopping, processing...")
            audio = rec.stop()
            notify(cfg, "Transcribing...", "low", persist=True, replace=True)
            if audio.size == 0:
                print("No audio captured.")
                notify(cfg, "No audio captured", "critical", replace=True)
                return
            duration = audio.shape[0] / cfg.sample_rate
            if duration < MIN_DURATION_SECS:
                print(f"Recording too short ({duration:.1f}s), skipping.")
                notify(cfg, "Recording too short", "low", replace=True)
                return
            if duration > WARN_DURATION_SECS:
                print(f"Warning: long recording ({duration:.0f}s), upload may be slow.", file=sys.stderr)
            processing = True
            try:
                text = transcribe(cfg, audio).strip()
                if text:
                    try:
                        copy_to_clipboard(text)
                        print("Transcription copied to clipboard.")
                        preview = text if len(text) <= 120 else text[:117] + "..."
                        notify(cfg, f"\u201c{preview}\u201d", replace=True)
                    except Exception as e:
                        print(f"Clipboard unavailable: {e}", file=sys.stderr)
                        print("Transcription (not copied):\n" + text)
                        notify(cfg, "Transcription ready (clipboard unavailable)", replace=True)
                else:
                    print("Empty transcription.")
                    notify(cfg, "Empty transcription", "low", replace=True)
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)
                err_msg = str(e)
                preview = err_msg if len(err_msg) <= 120 else err_msg[:117] + "..."
                notify(cfg, preview, "critical", replace=True)
            finally:
                processing = False

    print(f"Ready. Press {cfg.hotkey} to start/stop recording. Press <esc> to exit.")

    if sys.platform.startswith("linux"):
        session_type = (os.getenv("XDG_SESSION_TYPE") or "").lower()
        is_wayland = session_type == "wayland"
        print(f"Session: {session_type or 'unknown'}")

        pidfile_dir = Path.home() / ".cache" / "phonetic"
        pidfile_dir.mkdir(parents=True, exist_ok=True)
        pidfile_path = pidfile_dir / "pid"

        def write_pidfile() -> None:
            try:
                pidfile_path.write_text(str(os.getpid()), encoding="utf-8")
            except Exception as e:
                print(f"PID file write failed at {pidfile_path}: {e}", file=sys.stderr)

        def cleanup_pidfile() -> None:
            try:
                if pidfile_path.exists():
                    pidfile_path.unlink()
            except Exception:
                pass

        signal.signal(signal.SIGUSR1, lambda _s, _f: toggle_recording())
        write_pidfile()
        atexit.register(cleanup_pidfile)
        if pidfile_path.exists():
            print(f"Signal toggle enabled. Run: kill -USR1 $(cat {pidfile_path})")
        else:
            print(f"Warning: PID file not present at {pidfile_path}", file=sys.stderr)

        if is_wayland:
            print("Wayland session detected. Global hotkeys via Xlib are typically blocked.", file=sys.stderr)
            print("Tip: Create a desktop shortcut that runs:", file=sys.stderr)
            print(f"  kill -USR1 $(cat {pidfile_path})", file=sys.stderr)
            print("Press Ctrl+C to exit.")
            try:
                while True:
                    time.sleep(1.0)
            except KeyboardInterrupt:
                pass
            finally:
                if rec.is_recording:
                    rec.stop()
                time.sleep(0.05)
                cleanup_pidfile()
            return

        d = display.Display()
        root = d.screen().root

        def parse_hotkey(hk: str) -> tuple[int, int]:
            parts = [p for p in hk.lower().replace("<", "").replace(">", "").split("+") if p]
            mods = 0
            key = None
            for p in parts:
                if p in {"ctrl", "control"}:
                    mods |= X.ControlMask
                elif p in {"alt", "mod1"}:
                    mods |= X.Mod1Mask
                elif p in {"shift"}:
                    mods |= X.ShiftMask
                elif p in {"super", "win", "meta"}:
                    mods |= X.Mod4Mask
                else:
                    key = p
            if key is None:
                raise ValueError("No key specified in HOTKEY")
            keysym = XK.string_to_keysym(key)
            if keysym == 0:
                keysym = XK.string_to_keysym(key.upper())
            if keysym == 0:
                raise ValueError(f"Unsupported hotkey key: {key}")
            keycode = d.keysym_to_keycode(keysym)
            return keycode, mods

        keycode, mods = parse_hotkey(cfg.hotkey)
        esc_code = d.keysym_to_keycode(XK.XK_Escape)

        for lock in (0, X.LockMask):
            for num in (0, X.Mod2Mask):
                root.grab_key(keycode, mods | lock | num, True, X.GrabModeAsync, X.GrabModeAsync)
                root.grab_key(esc_code, 0 | lock | num, True, X.GrabModeAsync, X.GrabModeAsync)
        d.sync()

        print("(Using Xlib listener)")
        try:
            while True:
                ev = d.next_event()
                if ev.type == X.KeyPress:
                    if ev.detail == esc_code:
                        break
                    if ev.detail == keycode and (ev.state & mods) == mods:
                        toggle_recording()
        except KeyboardInterrupt:
            pass
        finally:
            if rec.is_recording:
                rec.stop()
            time.sleep(0.05)
            cleanup_pidfile()
    else:
        def on_press(key):
            if key == kb_nix.Key.esc:
                return False
            return True

        with kb_nix.GlobalHotKeys({cfg.hotkey: toggle_recording}) as h:
            with kb_nix.Listener(on_press=on_press) as l:
                try:
                    h.join()
                except KeyboardInterrupt:
                    pass
                finally:
                    if rec.is_recording:
                        rec.stop()
                    time.sleep(0.05)


if __name__ == "__main__":
    main()
