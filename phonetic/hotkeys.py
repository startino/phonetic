import atexit
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

from pynput import keyboard as kb


def validate_hotkey(hotkey: str) -> Optional[str]:
    """Validate a pynput hotkey string.

    Returns None if valid, or an error message string if invalid.
    """
    try:
        kb.HotKey.parse(hotkey)
        return None
    except (ValueError, TypeError) as e:
        return str(e)


class HotkeyManager:
    """Cross-platform global hotkey listener using pynput + SIGUSR1 fallback."""

    def __init__(self, hotkey: str, on_toggle: Callable[[], None]) -> None:
        self._hotkey = hotkey
        self._on_toggle = on_toggle
        self._listener: Optional[kb.GlobalHotKeys] = None
        self._thread: Optional[threading.Thread] = None
        self._pidfile_path: Optional[Path] = None

    def start(self) -> None:
        """Start listening for the global hotkey."""
        # Set up SIGUSR1 on Linux (Wayland fallback)
        if sys.platform.startswith("linux"):
            self._setup_sigusr1()

        # Start pynput GlobalHotKeys in a daemon thread
        self._listener = kb.GlobalHotKeys({self._hotkey: self._on_toggle})
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        """Stop the hotkey listener."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        self._cleanup_pidfile()

    def update_hotkey(self, new_hotkey: str) -> None:
        """Restart the listener with a new hotkey.

        Raises ValueError if the hotkey string is invalid.
        """
        error = validate_hotkey(new_hotkey)
        if error:
            raise ValueError(f"Invalid hotkey '{new_hotkey}': {error}")
        if self._listener is not None:
            self._listener.stop()
        self._hotkey = new_hotkey
        self._listener = kb.GlobalHotKeys({self._hotkey: self._on_toggle})
        self._listener.daemon = True
        self._listener.start()

    def _setup_sigusr1(self) -> None:
        """Set up SIGUSR1 handler and PID file for Linux."""
        signal.signal(signal.SIGUSR1, lambda _s, _f: self._on_toggle())

        pidfile_dir = Path.home() / ".cache" / "phonetic"
        pidfile_dir.mkdir(parents=True, exist_ok=True)
        self._pidfile_path = pidfile_dir / "pid"

        try:
            self._pidfile_path.write_text(str(os.getpid()), encoding="utf-8")
        except Exception as e:
            print(f"PID file write failed at {self._pidfile_path}: {e}", file=sys.stderr)

        atexit.register(self._cleanup_pidfile)

        if self._pidfile_path.exists():
            print(f"Signal toggle enabled. Run: kill -USR1 $(cat {self._pidfile_path})")

    def _cleanup_pidfile(self) -> None:
        """Remove the PID file."""
        if self._pidfile_path is not None:
            try:
                if self._pidfile_path.exists():
                    self._pidfile_path.unlink()
            except Exception:
                pass
