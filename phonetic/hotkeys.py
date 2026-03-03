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


# --- macOS Carbon hotkey manager ---
# Uses RegisterEventHotKey from the Carbon HIToolbox framework.
# This does NOT require Input Monitoring or Accessibility permissions.

# char → macOS virtual keycode (shared between Carbon and pynput managers)
_CHAR_TO_VK: dict[str, int] = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7,
    "c": 8, "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15,
    "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22,
    "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29,
    "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "l": 37,
    "j": 38, "k": 40, ",": 43, "/": 44, "n": 45, "m": 46, ".": 47,
    "space": 49, "`": 50,
}

# pynput-style modifier token → Carbon modifier mask value
_MOD_TO_CARBON: dict[str, int] = {
    "cmd": 256,      # cmdKey
    "shift": 512,    # shiftKey
    "ctrl": 4096,    # controlKey
    "alt": 2048,     # optionKey
}

_MOD_TOKENS: dict[str, str] = {
    "<cmd>": "cmd", "<shift>": "shift", "<ctrl>": "ctrl", "<alt>": "alt",
}


def _parse_hotkey(hotkey: str) -> tuple[frozenset[str], Optional[int]]:
    """Parse '<cmd>+<alt>+r' → (frozenset({'cmd', 'alt'}), 15)."""
    parts = hotkey.split("+")
    mods: set[str] = set()
    key_char: Optional[str] = None
    for p in parts:
        if p in _MOD_TOKENS:
            mods.add(_MOD_TOKENS[p])
        else:
            key_char = p
    vk = _CHAR_TO_VK.get(key_char) if key_char else None
    from .log import log
    log(f"hotkey parse: {hotkey!r} → mods={mods} key={key_char!r} vk={vk}")
    return frozenset(mods), vk


class _CarbonHotkeyManager:
    """macOS hotkey manager using Carbon RegisterEventHotKey.

    This API is part of the deprecated Carbon framework but remains the
    only way to register global hotkeys WITHOUT requiring Input Monitoring
    or Accessibility permissions.  It works with ad-hoc signed and
    sandboxed apps.
    """

    signal_only = False

    def __init__(self, hotkey: str, on_toggle: Callable[[], None]) -> None:
        self._hotkey = hotkey
        self._on_toggle = on_toggle
        self._hotkey_ref = None
        self._handler_ref = None
        self._required_mods, self._target_vk = _parse_hotkey(hotkey)

    def start(self) -> None:
        from .log import log

        if self._target_vk is None:
            log("carbon_hotkey: no virtual key found, cannot register")
            return

        # Build Carbon modifier mask
        modifier_mask = 0
        for mod in self._required_mods:
            modifier_mask |= _MOD_TO_CARBON.get(mod, 0)

        log(f"carbon_hotkey: registering vk={self._target_vk} modifiers={modifier_mask} (mods={self._required_mods})")

        try:
            import objc
            from quickmachotkey._MinimalHIToolbox import (
                EventTypeSpec,
                GetEventDispatcherTarget,
                GetEventParameter,
                InstallEventHandler,
                RegisterEventHotKey,
                kEventClassKeyboard,
                kEventHotKeyPressed,
                kEventParamDirectObject,
                typeEventHotKeyID,
            )
            from struct import unpack

            # Unique signature for our hotkey events
            PHON = unpack("@I", b"PHON")[0]
            HOT_KEY_ID = 1

            on_toggle = self._on_toggle

            @objc.callbackFor(InstallEventHandler)
            def _carbon_callback(callref, event, void):
                try:
                    result, actualType, actualSize, param = GetEventParameter(
                        event, kEventParamDirectObject, typeEventHotKeyID,
                        None, 8, None, None,
                    )
                    sig, hkid = unpack("@II", param)
                    if sig == PHON and hkid == HOT_KEY_ID:
                        log("carbon_hotkey: hotkey FIRED")
                        on_toggle()
                except Exception as exc:
                    log(f"carbon_hotkey: callback error: {exc}")
                return 0

            hotkey_spec = EventTypeSpec(
                eventClass=kEventClassKeyboard,
                eventKind=kEventHotKeyPressed,
            )

            result, handler_ref = InstallEventHandler(
                GetEventDispatcherTarget(), _carbon_callback,
                1, [hotkey_spec], None, None,
            )
            log(f"carbon_hotkey: InstallEventHandler result={result}")
            if result != 0:
                log(f"carbon_hotkey: FAILED to install event handler (result={result})")
                return
            self._handler_ref = handler_ref

            hotkey_id = (PHON, HOT_KEY_ID)
            result, hotkey_ref = RegisterEventHotKey(
                self._target_vk, modifier_mask, hotkey_id,
                GetEventDispatcherTarget(), 0, None,
            )
            log(f"carbon_hotkey: RegisterEventHotKey result={result}")
            if result != 0:
                log(f"carbon_hotkey: FAILED to register hotkey (result={result})")
                return
            self._hotkey_ref = hotkey_ref

            # prevent callback from being garbage collected
            self._callback = _carbon_callback

            log("carbon_hotkey: successfully registered")

        except Exception as exc:
            log(f"carbon_hotkey: EXCEPTION during setup: {exc}")
            import traceback
            log(f"carbon_hotkey: traceback: {traceback.format_exc()}")

    def stop(self) -> None:
        from .log import log
        if self._hotkey_ref is not None:
            try:
                from quickmachotkey._MinimalHIToolbox import UnregisterEventHotKey
                UnregisterEventHotKey(self._hotkey_ref)
                log("carbon_hotkey: unregistered")
            except Exception as exc:
                log(f"carbon_hotkey: unregister error: {exc}")
            self._hotkey_ref = None

    def update_hotkey(self, new_hotkey: str) -> None:
        """Update the hotkey — requires stop/start cycle."""
        self._hotkey = new_hotkey
        self._required_mods, self._target_vk = _parse_hotkey(new_hotkey)


class _PynputHotkeyManager(_PidFileMixin):
    """Hotkey manager using pynput Listener with vk-based matching on macOS,
    or GlobalHotKeys on other platforms. SIGUSR1 fallback on Linux."""

    signal_only = False

    _MOD_KEYS: dict[str, set[str]] = {
        "cmd": {"cmd", "cmd_r"},
        "shift": {"shift", "shift_r"},
        "ctrl": {"ctrl", "ctrl_l", "ctrl_r"},
        "alt": {"alt", "alt_l", "alt_r"},
    }

    def __init__(self, hotkey: str, on_toggle: Callable[[], None]) -> None:
        self._hotkey = hotkey
        self._on_toggle = on_toggle
        self._listener = None
        self._held_mods: set[str] = set()
        self._required_mods, self._target_vk = _parse_hotkey(hotkey)

    def start(self) -> None:
        self._setup_sigusr1(self._on_toggle)
        kb = _load_pynput()
        from .log import log

        if sys.platform == "darwin" and self._target_vk is not None:
            log(f"hotkey: using vk-based listener (mods={self._required_mods}, vk={self._target_vk})")
            self._listener = kb.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
            )
        else:
            log(f"hotkey: using GlobalHotKeys for {self._hotkey!r}")
            self._listener = kb.GlobalHotKeys({self._hotkey: self._on_toggle})
        self._listener.daemon = True
        self._listener.start()

    def _on_press(self, key) -> None:
        kb = _load_pynput()
        if isinstance(key, kb.Key):
            name = key.name
            for mod, names in self._MOD_KEYS.items():
                if name in names:
                    self._held_mods.add(mod)
                    return
            return
        vk = getattr(key, "vk", None)
        if vk == self._target_vk and self._held_mods == self._required_mods:
            self._on_toggle()

    def _on_release(self, key) -> None:
        kb = _load_pynput()
        if isinstance(key, kb.Key):
            name = key.name
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
        self._required_mods, self._target_vk = _parse_hotkey(new_hotkey)


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

    - macOS: _CarbonHotkeyManager (no permissions needed)
    - X11 / Windows: _PynputHotkeyManager (pynput + SIGUSR1 on Linux)
    - Wayland or pynput unavailable: _SignalOnlyHotkeyManager (SIGUSR1 only)
    """
    from .log import log

    if sys.platform == "darwin":
        try:
            log("HotkeyManager: trying Carbon (no permissions needed)")
            return _CarbonHotkeyManager(hotkey, on_toggle)
        except Exception as exc:
            log(f"HotkeyManager: Carbon failed: {exc}, falling back to pynput")

    if sys.platform.startswith("linux") and _is_wayland():
        return _SignalOnlyHotkeyManager(hotkey, on_toggle)

    if _load_pynput() is None:
        return _SignalOnlyHotkeyManager(hotkey, on_toggle)

    return _PynputHotkeyManager(hotkey, on_toggle)
