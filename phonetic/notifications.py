import subprocess
import sys
from typing import Optional


_notify_id: Optional[str] = None


def notify(body: str, urgency: str = "normal", persist: bool = False,
           replace: bool = False, enabled: bool = True,
           tray: object = None) -> None:
    """Send a desktop notification.

    Uses pystray notify when a tray is available, falls back to notify-send
    on Linux, then console print.

    Args:
        body: Notification body text.
        urgency: "low", "normal", or "critical".
        persist: If True, notification won't auto-dismiss.
        replace: If True, replaces the previously persisted notification.
        enabled: If False, skip entirely.
        tray: Optional TrayManager instance with a notify() method.
    """
    global _notify_id
    if not enabled:
        return

    # Try pystray notify first (cross-platform)
    if tray is not None:
        try:
            tray.notify("Phonetic", body)
            return
        except Exception:
            pass

    # Linux: use notify-send for richer notifications
    if sys.platform.startswith("linux"):
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
            return
        except Exception:
            pass

    # Final fallback: console
    print(f"[Phonetic] {body}")
