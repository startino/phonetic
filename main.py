import os
import sys
import time
import queue
import tempfile
import signal
import subprocess
import atexit
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Literal

import numpy as np
import sounddevice as sd
import soundfile as sf
import pyperclip
import httpx
from dotenv import load_dotenv

if sys.platform.startswith("linux"):
    # Linux: use python-xlib to avoid evdev build/runtime issues
    from Xlib import X, XK, display
else:
    # Non-Linux: use pynput
    from pynput import keyboard as kb_nix


Provider = Literal["openai", "azure"]


@dataclass
class Config:
    provider: Provider
    hotkey: str
    sample_rate: int
    channels: int
    openai_api_key: Optional[str]
    azure_endpoint: Optional[str]
    azure_api_key: Optional[str]
    azure_deployment: Optional[str]
    azure_api_version: str
    azure_task: str
    notify: bool
    whisper_prompt: Optional[str]
    # Optional post-process settings
    postprocess_provider: Optional[str]
    postprocess_model: Optional[str]
    postprocess_instruction: Optional[str]
    postprocess_openai_api_key: Optional[str]
    postprocess_azure_endpoint: Optional[str]
    postprocess_azure_api_key: Optional[str]
    postprocess_azure_deployment: Optional[str]
    postprocess_azure_api_version: Optional[str]


def load_config() -> Config:
    load_dotenv()
    provider = os.getenv("WHISPER_PROVIDER", "openai").strip().lower()
    if provider not in {"openai", "azure"}:
        print("WHISPER_PROVIDER must be 'openai' or 'azure'", file=sys.stderr)
        sys.exit(1)

    hotkey = os.getenv("HOTKEY", "<ctrl>+<alt>+r").strip()
    sample_rate = int(os.getenv("SAMPLE_RATE", "16000"))
    channels = int(os.getenv("CHANNELS", "1"))

    return Config(
        provider=provider,  # type: ignore[arg-type]
        hotkey=hotkey,
        sample_rate=sample_rate,
        channels=channels,
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        azure_api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
        azure_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
        azure_task=os.getenv("AZURE_OPENAI_TASK", "transcriptions").strip().lower(),
        notify=os.getenv("NOTIFY", "1").strip() not in {"0", "false", "no"},
        whisper_prompt=(os.getenv("WHISPER_PROMPT") or None),
        # Default provider to the same one used for Whisper if not set
        postprocess_provider=(os.getenv("POSTPROCESS_PROVIDER") or provider),
        postprocess_model=(os.getenv("POSTPROCESS_MODEL") or None),
        postprocess_instruction=(os.getenv("POSTPROCESS_INSTRUCTION") or None),
        # Default API keys/endpoints to Whisper's envs for convenience
        postprocess_openai_api_key=(os.getenv("POSTPROCESS_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY") or None),
        postprocess_azure_endpoint=(os.getenv("POSTPROCESS_AZURE_ENDPOINT") or os.getenv("AZURE_OPENAI_ENDPOINT") or None),
        postprocess_azure_api_key=(os.getenv("POSTPROCESS_AZURE_API_KEY") or os.getenv("AZURE_OPENAI_API_KEY") or None),
        postprocess_azure_deployment=(os.getenv("POSTPROCESS_AZURE_DEPLOYMENT") or os.getenv("AZURE_OPENAI_DEPLOYMENT") or None),
        postprocess_azure_api_version=(os.getenv("POSTPROCESS_AZURE_API_VERSION") or os.getenv("AZURE_OPENAI_API_VERSION") or None),
    )


def notify_linux(title: str, body: str = "", urgency: str = "normal") -> None:
    """Send a desktop notification on Linux via notify-send if available.

    Best-effort; silently ignore if notify-send is not present.
    """
    try:
        subprocess.run(
            ["notify-send", "--urgency", urgency, title, body],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


class Recorder:
    def __init__(self, sample_rate: int, channels: int) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self._q: "queue.Queue[np.ndarray]" = queue.Queue()
        self._stream: Optional[sd.InputStream] = None
        self._frames: list[np.ndarray] = []
        self._running = False

    def _callback(self, indata, frames, time_info, status):  # noqa: D401 - sd callback signature
        if status:
            # Print non-fatal stream status warnings
            print(status, file=sys.stderr)
        # Copy data to avoid referencing internal buffer
        self._q.put(indata.copy())

    def start(self) -> None:
        if self._running:
            return
        self._frames.clear()
        self._q = queue.Queue()
        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                callback=self._callback,
            )
            self._stream.start()
            self._running = True
        except Exception as e:
            # Common causes: no input device, permissions (macOS), ALSA issues (Linux)
            print(f"Audio input error: {e}", file=sys.stderr)
            self._stream = None
            self._running = False

    def stop(self) -> np.ndarray:
        if not self._running:
            return np.empty((0, self.channels), dtype=np.float32)
        assert self._stream is not None
        self._stream.stop()
        self._stream.close()
        self._stream = None
        self._running = False
        # Drain queue
        while not self._q.empty():
            try:
                self._frames.append(self._q.get_nowait())
            except queue.Empty:
                break
        if not self._frames:
            return np.empty((0, self.channels), dtype=np.float32)
        audio = np.concatenate(self._frames, axis=0)
        # Clip to [-1, 1] and convert to float32 if needed
        audio = np.clip(audio, -1.0, 1.0).astype(np.float32)
        return audio


def save_wav(audio: np.ndarray, sample_rate: int) -> str:
    fd, path = tempfile.mkstemp(prefix="whisper_record_", suffix=".wav")
    os.close(fd)
    with sf.SoundFile(path, mode="w", samplerate=sample_rate, channels=audio.shape[1] if audio.ndim > 1 else 1, subtype="PCM_16") as f:
        f.write(audio)
    return path


def transcribe_openai(file_path: str, api_key: str, prompt: Optional[str]) -> str:
    url = "https://api.openai.com/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"}
    with open(file_path, "rb") as f:
        files = {
            "file": (os.path.basename(file_path), f, "audio/wav"),
        }
        data = {"model": "whisper-1"}
        if prompt:
            data["prompt"] = prompt
        with httpx.Client(timeout=300) as client:
            resp = client.post(url, headers=headers, files=files, data=data)
            resp.raise_for_status()
            j = resp.json()
            # Both {text: "..."} and variants may appear; prefer "text"
            return j.get("text") or j.get("transcript") or ""


def transcribe_azure(file_path: str, endpoint: str, api_key: str, deployment: str, api_version: str, task: str, prompt: Optional[str]) -> str:
    """
    Handle Azure endpoint variants:
    - If `endpoint` is a base resource URL (e.g., https://<resource>.openai.azure.com), build the standard path
      /openai/deployments/{deployment}/audio/{task}?api-version={api_version}
    - If `endpoint` is already a full target URI copied from Azure Studio (may include /audio/transcriptions or /audio/translations and api-version), use it as-is.
    """
    base = endpoint.rstrip("/")
    if "/audio/transcriptions" in base or "/audio/translations" in base:
        url = base
        # Ensure api-version present
        if "api-version=" not in url and api_version:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}api-version={api_version}"
    else:
        task_path = "translations" if task == "translations" else "transcriptions"
        url = f"{base}/openai/deployments/{deployment}/audio/{task_path}?api-version={api_version}"
    headers = {"api-key": api_key}
    with open(file_path, "rb") as f:
        files = {
            "file": (os.path.basename(file_path), f, "audio/wav"),
        }
        # Azure ignores model in body, uses deployment; response mirrors OpenAI
        data = {}
        if prompt:
            data["prompt"] = prompt
        with httpx.Client(timeout=300) as client:
            resp = client.post(url, headers=headers, files=files, data=data)
            resp.raise_for_status()
            j = resp.json()
            return j.get("text") or j.get("transcript") or ""


def postprocess_text(cfg: Config, original: str) -> Optional[str]:
    """Optionally rewrite the transcript using an LLM according to instruction.

    Returns the rewritten text, or None if not configured or on failure.
    """
    provider = (cfg.postprocess_provider or "").strip().lower()
    instruction = (cfg.postprocess_instruction or "").strip()
    model = (cfg.postprocess_model or "").strip()
    if not provider or not instruction or not model:
        return None

    try:
        if provider == "openai":
            api_key = cfg.postprocess_openai_api_key
            if not api_key:
                return None
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": original},
                ],
                "temperature": 0.2,
            }
            with httpx.Client(timeout=120) as client:
                r = client.post(url, headers=headers, json=payload)
                r.raise_for_status()
                data = r.json()
                return (data.get("choices") or [{}])[0].get("message", {}).get("content")

        if provider == "azure":
            if not (cfg.postprocess_azure_endpoint and cfg.postprocess_azure_api_key and cfg.postprocess_azure_deployment and cfg.postprocess_azure_api_version):
                return None
            base = cfg.postprocess_azure_endpoint.rstrip("/")
            url = f"{base}/openai/deployments/{cfg.postprocess_azure_deployment}/chat/completions?api-version={cfg.postprocess_azure_api_version}"
            headers = {"api-key": cfg.postprocess_azure_api_key, "Content-Type": "application/json"}
            payload = {
                "messages": [
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": original},
                ],
                "temperature": 0.2,
            }
            with httpx.Client(timeout=120) as client:
                r = client.post(url, headers=headers, json=payload)
                r.raise_for_status()
                data = r.json()
                # Azure returns same schema for chat/completions
                return (data.get("choices") or [{}])[0].get("message", {}).get("content")
    except Exception:
        return None

    return None


def main() -> None:
    cfg = load_config()

    # Validate provider env
    if cfg.provider == "openai":
        if not cfg.openai_api_key:
            print("OPENAI_API_KEY is required for provider 'openai'", file=sys.stderr)
            sys.exit(1)
    else:
        missing = []
        if not cfg.azure_endpoint:
            missing.append("AZURE_OPENAI_ENDPOINT")
        if not cfg.azure_api_key:
            missing.append("AZURE_OPENAI_API_KEY")
        if not cfg.azure_deployment:
            missing.append("AZURE_OPENAI_DEPLOYMENT")
        if missing:
            print("Missing Azure config: " + ", ".join(missing), file=sys.stderr)
            sys.exit(1)

    rec = Recorder(sample_rate=cfg.sample_rate, channels=cfg.channels)
    is_recording = {"value": False}

    def toggle_recording():
        if not is_recording["value"]:
            print(f"Recording... Press {cfg.hotkey} to stop.")
            rec.start()
            is_recording["value"] = True
            if cfg.notify and sys.platform.startswith("linux"):
                notify_linux("Simple Whisper", "Recording started", "low")
        else:
            print("Stopping, processing...")
            audio = rec.stop()
            is_recording["value"] = False
            if cfg.notify and sys.platform.startswith("linux"):
                notify_linux("Simple Whisper", "Recording stopped", "low")
            if audio.size == 0:
                print("No audio captured.")
                return
            wav_path = save_wav(audio, cfg.sample_rate)
            try:
                if cfg.provider == "openai":
                    assert cfg.openai_api_key is not None
                    text = transcribe_openai(wav_path, cfg.openai_api_key, cfg.whisper_prompt)
                else:
                    assert cfg.azure_endpoint and cfg.azure_api_key and cfg.azure_deployment
                    text = transcribe_azure(
                        wav_path,
                        cfg.azure_endpoint,
                        cfg.azure_api_key,
                        cfg.azure_deployment,
                        cfg.azure_api_version,
                        cfg.azure_task,
                        cfg.whisper_prompt,
                    )
                text = (text or "").strip()
                if text:
                    try:
                        pyperclip.copy(text)
                        print("Transcription copied to clipboard.")
                        if cfg.notify and sys.platform.startswith("linux"):
                            preview = text if len(text) <= 120 else text[:117] + "..."
                            notify_linux("Simple Whisper", f"Copied: {preview}", "normal")
                    except Exception as e:
                        # Common on Linux when xclip/xsel is missing
                        print(f"Clipboard unavailable: {e}", file=sys.stderr)
                        print("Transcription (not copied):\n" + text)
                        if cfg.notify and sys.platform.startswith("linux"):
                            notify_linux("Simple Whisper", "Transcription ready (clipboard unavailable)", "normal")
                else:
                    print("Empty transcription.")
                    if cfg.notify and sys.platform.startswith("linux"):
                        notify_linux("Simple Whisper", "Empty transcription", "low")
                # Optional post-process using LLM to restyle text
                if text:
                    refined = postprocess_text(cfg, text)
                    if refined:
                        try:
                            pyperclip.copy(refined)
                            print("Post-processed transcription copied to clipboard.")
                            if cfg.notify and sys.platform.startswith("linux"):
                                p2 = refined if len(refined) <= 120 else refined[:117] + "..."
                                notify_linux("Simple Whisper", f"Copied (restyled): {p2}", "normal")
                        except Exception:
                            pass
                
            except httpx.HTTPError as e:
                print(f"HTTP error: {e}", file=sys.stderr)
                if cfg.notify and sys.platform.startswith("linux"):
                    notify_linux("Simple Whisper", "HTTP error during transcription", "critical")
            except Exception as e:  # noqa: BLE001 - catch top-level to keep app running
                print(f"Error: {e}", file=sys.stderr)
                if cfg.notify and sys.platform.startswith("linux"):
                    notify_linux("Simple Whisper", "Error during transcription", "critical")
            finally:
                try:
                    os.remove(wav_path)
                except Exception:
                    pass

    # Set up global hotkey
    print(f"Ready. Press {cfg.hotkey} to start/stop recording. Press <esc> to exit.")

    if sys.platform.startswith("linux"):
        # On Wayland, global grabs generally don't work. Provide a signal-based fallback.
        session_type = (os.getenv("XDG_SESSION_TYPE") or "").lower()
        is_wayland = session_type == "wayland"
        print(f"Session: {session_type or 'unknown'}")

        # Signal-based toggle setup (used on Wayland; also helpful generally)
        pidfile_dir = Path.home() / ".cache" / "simple-whisper"
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

        def handle_sigusr1(_signum, _frame) -> None:  # noqa: D401 - signal signature
            toggle_recording()

        signal.signal(signal.SIGUSR1, handle_sigusr1)
        write_pidfile()
        atexit.register(cleanup_pidfile)
        if pidfile_path.exists():
            print(f"Signal toggle enabled. Run: kill -USR1 $(cat {pidfile_path})")
        else:
            print(f"Warning: PID file not present at {pidfile_path}", file=sys.stderr)

        if is_wayland:
            # Wayland fallback: advise user to bind a desktop shortcut to send SIGUSR1
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
                if is_recording["value"]:
                    rec.stop()
                time.sleep(0.05)
                cleanup_pidfile()
            return

        # Simple Xlib-based hotkey listener for one combo + ESC (X11/XWayland)
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
                # Try uppercase
                keysym = XK.string_to_keysym(key.upper())
            if keysym == 0:
                raise ValueError(f"Unsupported hotkey key: {key}")
            keycode = d.keysym_to_keycode(keysym)
            return keycode, mods

        keycode, mods = parse_hotkey(cfg.hotkey)
        esc_code = d.keysym_to_keycode(XK.XK_Escape)

        # Grab with variations for NumLock/CapsLock
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
            if is_recording["value"]:
                rec.stop()
            time.sleep(0.05)
            cleanup_pidfile()
    else:
        # Non-Linux: use pynput GlobalHotKeys
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
                    if is_recording["value"]:
                        rec.stop()
                    time.sleep(0.05)


if __name__ == "__main__":
    main()
