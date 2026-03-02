import atexit
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

from .platform_utils import _is_wayland

# Lazy-loaded pynput keyboard module (None if unavailable)
_kb = None
_pynput_error: Optional[str] = None


def _load_pynput():
    """Lazily load pynput.keyboard, returning the module or None."""
    global _kb, _pynput_error
    if _kb is not None:
        return _kb
    if _pynput_error is not None:
        return None
    try:
        from pynput import keyboard as kb
        _kb = kb
        return _kb
    except (ImportError, Exception) as e:
        _pynput_error = str(e)
        return None


def validate_hotkey(hotkey: str) -> Optional[str]:
    """Validate a pynput hotkey string.

    Returns None if valid, or an error message string if invalid.
    When pynput is unavailable (e.g. Wayland), always returns None (valid).
    """
    kb = _load_pynput()
    if kb is None:
        return None
    try:
        kb.HotKey.parse(hotkey)
        return None
    except (ValueError, TypeError) as e:
        return str(e)


class _PidFileMixin:
    """Shared SIGUSR1 + PID file logic for Linux hotkey managers."""

    _pidfile_path: Optional[Path] = None

    def _setup_sigusr1(self, on_toggle: Callable[[], None]) -> None:
        """Set up SIGUSR1 handler and PID file for Linux."""
        if not sys.platform.startswith("linux"):
            return

        signal.signal(signal.SIGUSR1, lambda _s, _f: on_toggle())

        pidfile_dir = Path.home() / ".cache" / "phonetic"
        pidfile_dir.mkdir(parents=True, exist_ok=True)
        self._pidfile_path = pidfile_dir / "pid"

        try:
            self._pidfile_path.write_text(str(os.getpid()), encoding="utf-8")
        except Exception as e:
            print(f"PID file write failed at {self._pidfile_path}: {e}", file=sys.stderr)

        atexit.register(self._cleanup_pidfile)

    def _cleanup_pidfile(self) -> None:
        """Remove the PID file."""
        if self._pidfile_path is not None:
            try:
                if self._pidfile_path.exists():
                    self._pidfile_path.unlink()
            except Exception:
                pass

    @property
    def pidfile_path(self) -> Optional[Path]:
        return self._pidfile_path


class _PynputHotkeyManager(_PidFileMixin):
    """Hotkey manager using pynput GlobalHotKeys + SIGUSR1 fallback on Linux."""

    signal_only = False

    def __init__(self, hotkey: str, on_toggle: Callable[[], None]) -> None:
        self._hotkey = hotkey
        self._on_toggle = on_toggle
        self._listener = None

    def start(self) -> None:
        self._setup_sigusr1(self._on_toggle)
        kb = _load_pynput()
        self._listener = kb.GlobalHotKeys({self._hotkey: self._on_toggle})
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        self._cleanup_pidfile()

    def update_hotkey(self, new_hotkey: str) -> None:
        error = validate_hotkey(new_hotkey)
        if error:
            raise ValueError(f"Invalid hotkey '{new_hotkey}': {error}")
        self._hotkey = new_hotkey
        # Don't recreate the pynput listener — on macOS, creating a new
        # GlobalHotKeys listener after stopping one crashes with
        # dispatch_assert_queue_fail in TSMGetInputSourceProperty.
        # The new hotkey takes effect on next restart.


class _SignalOnlyHotkeyManager(_PidFileMixin):
    """SIGUSR1-only hotkey manager for Wayland or when pynput is unavailable."""

    signal_only = True

    def __init__(self, hotkey: str, on_toggle: Callable[[], None]) -> None:
        self._hotkey = hotkey
        self._on_toggle = on_toggle

    def start(self) -> None:
        self._setup_sigusr1(self._on_toggle)

    def stop(self) -> None:
        self._cleanup_pidfile()

    def update_hotkey(self, new_hotkey: str) -> None:
        self._hotkey = new_hotkey


def HotkeyManager(hotkey: str, on_toggle: Callable[[], None]):
    """Factory: returns the appropriate hotkey manager for the current platform.

    - X11 / macOS / Windows: _PynputHotkeyManager (pynput + SIGUSR1 on Linux)
    - Wayland or pynput unavailable: _SignalOnlyHotkeyManager (SIGUSR1 only)
    """
    if sys.platform.startswith("linux") and _is_wayland():
        return _SignalOnlyHotkeyManager(hotkey, on_toggle)

    if _load_pynput() is None:
        return _SignalOnlyHotkeyManager(hotkey, on_toggle)

    return _PynputHotkeyManager(hotkey, on_toggle)
