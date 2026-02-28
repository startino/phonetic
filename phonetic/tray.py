import queue
import sys
import threading
from typing import Optional

from PIL import Image, ImageDraw

try:
    import pystray
except ImportError:
    pystray = None


def _make_icon(color: str = "#cccccc", size: int = 64) -> Image.Image:
    """Generate a simple microphone icon programmatically."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Microphone body (rounded rectangle approximated by ellipse + rect)
    mic_w = size // 3
    mic_h = size // 2
    mic_x = (size - mic_w) // 2
    mic_y = size // 8

    # Mic head (ellipse top)
    draw.ellipse(
        [mic_x, mic_y, mic_x + mic_w, mic_y + mic_w],
        fill=color,
    )
    # Mic body (rectangle)
    draw.rectangle(
        [mic_x, mic_y + mic_w // 2, mic_x + mic_w, mic_y + mic_h],
        fill=color,
    )
    # Mic bottom (ellipse)
    draw.ellipse(
        [mic_x, mic_y + mic_h - mic_w // 2, mic_x + mic_w, mic_y + mic_h + mic_w // 2],
        fill=color,
    )
    # Stand
    stand_x = size // 2
    stand_top = mic_y + mic_h + mic_w // 4
    stand_bot = stand_top + size // 6
    draw.line([(stand_x, stand_top), (stand_x, stand_bot)], fill=color, width=max(2, size // 16))
    # Base
    base_w = size // 3
    draw.line(
        [(stand_x - base_w // 2, stand_bot), (stand_x + base_w // 2, stand_bot)],
        fill=color, width=max(2, size // 16),
    )

    return img


class TrayManager:
    """System tray icon manager."""

    def __init__(self, msg_queue: "queue.Queue[str]") -> None:
        self._msg_queue = msg_queue
        self._icon: Optional["pystray.Icon"] = None
        self._recording = False
        self._idle_icon = _make_icon("#cccccc")
        self._recording_icon = _make_icon("#ff4444")
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
