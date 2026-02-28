import os
import sys


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


def is_frozen() -> bool:
    """True when running as a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def has_display() -> bool:
    """Check if a display server is available."""
    if sys.platform == "darwin":
        return True
    if sys.platform == "win32":
        return True
    # Linux: check for X11 or Wayland
    return bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))
