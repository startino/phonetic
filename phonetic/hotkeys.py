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
    """Hotkey manager using pynput Listener with vk-based matching on macOS,
    or GlobalHotKeys on other platforms. SIGUSR1 fallback on Linux."""

    signal_only = False

    # macOS: char → virtual keycode (Option key composes characters, so
    # GlobalHotKeys can't match e.g. <cmd>+<alt>+r because it sees '®').
    _CHAR_TO_VK: dict[str, int] = {
        "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7,
        "c": 8, "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15,
        "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22,
        "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29,
        "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "l": 37,
        "j": 38, "k": 40, ",": 43, "/": 44, "n": 45, "m": 46, ".": 47,
        "space": 49, "`": 50,
    }

    # pynput Key.name values that map to each modifier
    _MOD_KEYS: dict[str, set[str]] = {
        "cmd": {"cmd", "cmd_r"},
        "shift": {"shift", "shift_r"},
        "ctrl": {"ctrl", "ctrl_l", "ctrl_r"},
        "alt": {"alt", "alt_l", "alt_r"},
    }

    _MOD_TOKENS: dict[str, str] = {
        "<cmd>": "cmd", "<shift>": "shift", "<ctrl>": "ctrl", "<alt>": "alt",
    }

    def __init__(self, hotkey: str, on_toggle: Callable[[], None]) -> None:
        self._hotkey = hotkey
        self._on_toggle = on_toggle
        self._listener = None
        self._held_mods: set[str] = set()
        self._required_mods, self._target_vk = self._parse_hotkey(hotkey)

    @classmethod
    def _parse_hotkey(cls, hotkey: str) -> tuple[frozenset[str], Optional[int]]:
        """Parse '<cmd>+<alt>+r' → (frozenset({'cmd', 'alt'}), 15)."""
        parts = hotkey.split("+")
        mods: set[str] = set()
        key_char: Optional[str] = None
        for p in parts:
            if p in cls._MOD_TOKENS:
                mods.add(cls._MOD_TOKENS[p])
            else:
                key_char = p
        vk = cls._CHAR_TO_VK.get(key_char) if key_char else None
        from .log import log
        log(f"hotkey parse: {hotkey!r} → mods={mods} key={key_char!r} vk={vk}")
        return frozenset(mods), vk

    def start(self) -> None:
        self._setup_sigusr1(self._on_toggle)
        kb = _load_pynput()
        from .log import log

        # Log Input Monitoring permission state right before creating listener
        if sys.platform == "darwin":
            try:
                from Quartz import CGPreflightListenEventAccess
                allowed = CGPreflightListenEventAccess()
                log(f"hotkey.start: CGPreflightListenEventAccess={allowed}")
            except Exception as exc:
                log(f"hotkey.start: input monitoring check failed: {exc}")

            try:
                from AppKit import NSApplication
                app = NSApplication.sharedApplication()
                policy = app.activationPolicy()
                log(f"hotkey.start: activationPolicy={policy} (0=Regular, 1=Accessory, 2=Prohibited)")
            except Exception as exc:
                log(f"hotkey.start: activationPolicy check failed: {exc}")

        if sys.platform == "darwin" and self._target_vk is not None:
            # macOS: use vk-based matching (GlobalHotKeys fails with alt/option
            # because Option composes characters, e.g. Alt+R → '®' not 'r')
            log(f"hotkey: using vk-based listener (mods={self._required_mods}, vk={self._target_vk})")
            self._listener = kb.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
            )
        else:
            log(f"hotkey: using GlobalHotKeys for {self._hotkey!r}")
            self._listener = kb.GlobalHotKeys({self._hotkey: self._on_toggle})
        self._listener.daemon = True
        log(f"hotkey.start: calling listener.start() (thread={threading.current_thread().name})")
        self._listener.start()
        log(f"hotkey.start: listener.start() returned, listener.is_alive()={self._listener.is_alive()}")

        # Check listener thread state after a brief delay
        import time
        time.sleep(0.2)
        log(f"hotkey.start: after 200ms, listener.is_alive()={self._listener.is_alive()}")

        # On macOS, inspect the CGEventTap via pynput internals
        if sys.platform == "darwin":
            try:
                tap = getattr(self._listener, '_tap', None)
                log(f"hotkey.start: listener._tap={tap}")
                if tap is not None:
                    is_enabled = getattr(tap, 'is_enabled', None)
                    log(f"hotkey.start: tap.is_enabled={is_enabled}")
            except Exception as exc:
                log(f"hotkey.start: tap inspection failed: {exc}")
            # Also try to inspect _loop and _port
            for attr in ('_loop', '_port', '_tap', '_event_mask'):
                val = getattr(self._listener, attr, 'MISSING')
                log(f"hotkey.start: listener.{attr}={val}")

    def _on_press(self, key) -> None:
        from .log import log
        kb = _load_pynput()
        if isinstance(key, kb.Key):
            name = key.name
            log(f"hotkey _on_press: special key={name}")
            for mod, names in self._MOD_KEYS.items():
                if name in names:
                    self._held_mods.add(mod)
                    return
            return
        # Regular key — check vk match
        vk = getattr(key, "vk", None)
        char = getattr(key, "char", None)
        log(f"hotkey _on_press: char={char!r} vk={vk} target_vk={self._target_vk} held={self._held_mods} required={self._required_mods}")
        if vk == self._target_vk and self._held_mods == self._required_mods:
            log("hotkey _on_press: MATCH — firing on_toggle")
            self._on_toggle()

    def _on_release(self, key) -> None:
        from .log import log
        kb = _load_pynput()
        if isinstance(key, kb.Key):
            name = key.name
            log(f"hotkey _on_release: special key={name}")
            for mod, names in self._MOD_KEYS.items():
                if name in names:
                    self._held_mods.discard(mod)
                    return

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
        self._required_mods, self._target_vk = self._parse_hotkey(new_hotkey)
        # Don't recreate the pynput listener — on macOS, creating a new
        # Listener after stopping one crashes with
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
