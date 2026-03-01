import os
import queue
import sys
import threading
from typing import Optional

from PIL import Image, ImageDraw

try:
    import pystray
except ImportError:
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
        self._idle_icon = _load_icon("icon.png")
        # Try pre-generated recording icon, fall back to runtime overlay
        rec_path = os.path.join(_assets_dir(), "icon_recording.png")
        if os.path.exists(rec_path):
            self._recording_icon = _load_icon("icon_recording.png")
        else:
            self._recording_icon = _add_recording_dot(self._idle_icon)
        self._thread: Optional[threading.Thread] = None

    def _build_menu(self) -> "pystray.Menu":
        return pystray.Menu(
            pystray.MenuItem(
                lambda _: "Status: Recording" if self._recording else "Status: Idle",
                None,
                enabled=False,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda _: "Stop Recording" if self._recording else "Start Recording",
                lambda _icon, _item: self._msg_queue.put("toggle_recording"),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Settings...", lambda _icon, _item: self._msg_queue.put("show_settings")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda _icon, _item: self._msg_queue.put("quit")),
        )

    def set_state(self, recording: bool) -> None:
        """Update tray icon to reflect recording state."""
        self._recording = recording
        if self._icon is not None:
            self._icon.icon = self._recording_icon if recording else self._idle_icon
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
