import os
import queue
import sys
import threading
from typing import Optional

from PIL import Image, ImageDraw

try:
    import pystray
except Exception:
    # Broad on purpose: pystray selects a backend AT IMPORT and the X11 backend
    # opens the display immediately, raising Xlib.error.DisplayNameError (NOT an
    # ImportError) when there is no display. Catching only ImportError let that
    # escape and crash any headless process that imported this module.
    pystray = None


def _assets_dir() -> str:
    """Resolve path to the assets directory (works in dev and PyInstaller)."""
    if getattr(sys, "frozen", False):
        # PyInstaller bundles assets alongside the executable
        return os.path.join(sys._MEIPASS, "assets")
    # Dev mode: assets/ is at the repo root, one level up from phonetic/
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def _load_icon(name: str, size: int = 64) -> Image.Image:
    """Load an icon from assets, or generate a fallback colored square."""
    path = os.path.join(_assets_dir(), name)
    try:
        img = Image.open(path).convert("RGBA")
        return img.resize((size, size), Image.LANCZOS)
    except (FileNotFoundError, OSError):
        # Fallback: colored square to prevent crash
        img = Image.new("RGBA", (size, size), "#444444")
        draw = ImageDraw.Draw(img)
        draw.ellipse([size // 4, size // 4, 3 * size // 4, 3 * size // 4], fill="#cccccc")
        return img


def _add_recording_dot(icon: Image.Image) -> Image.Image:
    """Overlay a red recording dot on the bottom-right of the icon."""
    img = icon.copy()
    size = img.width
    draw = ImageDraw.Draw(img)

    dot_r = size // 6
    margin = size // 16
    cx = size - margin - dot_r
    cy = size - margin - dot_r

    outline = dot_r // 6 or 1
    draw.ellipse(
        [cx - dot_r - outline, cy - dot_r - outline, cx + dot_r + outline, cy + dot_r + outline],
        fill="white",
    )
    draw.ellipse(
        [cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
        fill="#ff2222",
    )
    return img


class TrayManager:
    """System tray icon manager."""

    def __init__(self, msg_queue: "queue.Queue[str]") -> None:
        self._msg_queue = msg_queue
        self._icon: Optional["pystray.Icon"] = None
        self._recording = False
        self._recording_profile_id = ""  # which profile is mid-recording
        self._idle_icon = _load_icon("icon_tray.png")
        # Try pre-generated recording icon, fall back to runtime overlay
        rec_path = os.path.join(_assets_dir(), "icon_tray_recording.png")
        if os.path.exists(rec_path):
            self._recording_icon = _load_icon("icon_tray_recording.png")
        else:
            self._recording_icon = _add_recording_dot(self._idle_icon)
        self._thread: Optional[threading.Thread] = None

        # Device selection state
        self._selected_device: Optional[int] = None  # None = "Default"
        self._default_device: Optional[int] = None
        self._input_devices: list[dict] = []

        # Profiles listed directly in the menu (id, name, hotkey) so the user
        # picks exactly which profile to record with. There is no default.
        self._profiles: list = []

    def set_profiles(self, profiles: list) -> None:
        """Set the profiles shown as direct record entries in the tray menu."""
        self._profiles = list(profiles)
        if self._icon is not None:
            self._icon.menu = self._build_menu()
            self._icon.update_menu()

    def set_device(self, device: Optional[int], default_device: Optional[int]) -> None:
        """Set the current and default device (called by App after init)."""
        self._selected_device = device
        self._default_device = default_device
        self._refresh_devices()

    def _refresh_devices(self) -> None:
        """Refresh the cached list of input devices."""
        from .audio_detect import list_input_devices
        self._input_devices = list_input_devices()

    def _build_device_submenu(self) -> "pystray.Menu":
        """Build a radio-style submenu for audio device selection."""
        items = [
            pystray.MenuItem(
                "Default (auto-detect)",
                self._make_device_callback(None),
                checked=self._make_device_check(None),
                enabled=not self._recording,
            ),
            pystray.Menu.SEPARATOR,
        ]
        for dev in self._input_devices:
            idx = dev["index"]
            items.append(pystray.MenuItem(
                dev["name"],
                self._make_device_callback(idx),
                checked=self._make_device_check(idx),
                enabled=not self._recording,
            ))
        return pystray.Menu(*items)

    def _make_device_callback(self, idx: Optional[int]):
        """Factory to avoid closure-over-loop-variable bug."""
        def callback(_icon, _item):
            self._on_device_selected(idx)
        return callback

    def _make_device_check(self, idx: Optional[int]):
        """Factory for the checked predicate of a device menu item."""
        def check(_item):
            return self._selected_device == idx
        return check

    def _on_device_selected(self, idx: Optional[int]) -> None:
        """Handle a device selection from the submenu."""
        if idx == self._selected_device:
            return
        self._selected_device = idx
        self._msg_queue.put(("device_changed", idx))
        if idx is not None and idx != self._default_device:
            self.notify("Phonetic", "Switched away from the default audio device")
        if self._icon is not None:
            self._icon.update_menu()

    def _make_profile_callback(self, profile_id: str):
        """Factory to avoid closure-over-loop-variable bug."""
        def callback(_icon, _item):
            self._msg_queue.put(("toggle_recording", profile_id))
        return callback

    def _profile_menu_items(self) -> list:
        """One direct record entry per profile — no submenu, no generic toggle.

        Each entry records with THAT profile. While recording, the active
        profile's row becomes 'Stop' and the others are disabled so the only
        next action is to stop the in-flight recording.
        """
        if not self._profiles:
            return [pystray.MenuItem("No profiles — open Settings", None, enabled=False)]

        items = []
        for p in self._profiles:
            pid = getattr(p, "id", "")
            name = getattr(p, "name", "") or "(unnamed)"
            hotkey = getattr(p, "hotkey", "")
            is_active = self._recording and pid == self._recording_profile_id
            if is_active:
                label = f"■  Stop: {name}"
            else:
                label = f"Record: {name}" + (f"  ({hotkey})" if hotkey else "")
            items.append(pystray.MenuItem(
                label,
                self._make_profile_callback(pid),
                # While recording, only the active profile's row is enabled.
                enabled=(not self._recording) or is_active,
            ))
        return items

    def _build_menu(self) -> "pystray.Menu":
        return pystray.Menu(
            pystray.MenuItem(
                lambda _: "Status: Recording" if self._recording else "Status: Idle",
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            *self._profile_menu_items(),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Audio Device",
                self._build_device_submenu(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Settings...", lambda _icon, _item: self._msg_queue.put("show_settings")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda _icon, _item: self._msg_queue.put("quit")),
        )

    def set_state(self, recording: bool, profile_id: str = "") -> None:
        """Update tray icon + menu to reflect recording state.

        ``profile_id`` is the profile currently recording (so its row shows the
        Stop affordance and the others disable). Empty when idle.
        """
        self._recording = recording
        self._recording_profile_id = profile_id if recording else ""
        if self._icon is not None:
            self._icon.icon = self._recording_icon if recording else self._idle_icon
            self._icon.menu = self._build_menu()
            self._icon.update_menu()

    def notify(self, title: str, body: str) -> None:
        """Show a tray notification."""
        if self._icon is not None:
            try:
                self._icon.notify(body, title)
            except Exception:
                pass

    def run(self) -> None:
        """Start the tray icon in a daemon thread."""
        if pystray is None:
            return

        self._icon = pystray.Icon(
            "phonetic",
            icon=self._idle_icon,
            title="Phonetic",
            menu=self._build_menu(),
        )

        if sys.platform == "darwin":
            # macOS requires run_detached for non-main thread
            self._icon.run_detached()
        else:
            self._thread = threading.Thread(target=self._icon.run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Stop the tray icon."""
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
