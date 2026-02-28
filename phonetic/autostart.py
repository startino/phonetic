import os
import sys
from pathlib import Path

from .platform_utils import is_frozen


def _get_command() -> list[str]:
    """Get the command to launch Phonetic."""
    if is_frozen():
        return [sys.executable]
    # Running via Python/uv — need -m phonetic to launch the package
    return [sys.executable, "-m", "phonetic"]


# --- macOS: LaunchAgent plist ---

def _launchagent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "com.startino.phonetic.plist"


def _set_autostart_macos(enabled: bool) -> None:
    import plistlib

    path = _launchagent_path()
    if enabled:
        plist = {
            "Label": "com.startino.phonetic",
            "ProgramArguments": _get_command(),
            "RunAtLoad": True,
            "KeepAlive": False,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            plistlib.dump(plist, f)
    else:
        if path.exists():
            path.unlink()


def _is_autostart_macos() -> bool:
    return _launchagent_path().exists()


# --- Windows: Registry ---

_WIN_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_WIN_REG_NAME = "Phonetic"


def _set_autostart_windows(enabled: bool) -> None:
    import winreg

    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_REG_KEY, 0, winreg.KEY_SET_VALUE)
    try:
        if enabled:
            cmd = _get_command()
            value = " ".join(f'"{part}"' for part in cmd)
            winreg.SetValueEx(key, _WIN_REG_NAME, 0, winreg.REG_SZ, value)
        else:
            try:
                winreg.DeleteValue(key, _WIN_REG_NAME)
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


def _is_autostart_windows() -> bool:
    import winreg

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_REG_KEY, 0, winreg.KEY_QUERY_VALUE)
        try:
            winreg.QueryValueEx(key, _WIN_REG_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


# --- Linux: XDG autostart .desktop ---

def _desktop_file_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(xdg) / "autostart" / "phonetic.desktop"


def _set_autostart_linux(enabled: bool) -> None:
    path = _desktop_file_path()
    if enabled:
        exec_line = " ".join(_get_command())
        content = f"""[Desktop Entry]
Type=Application
Name=Phonetic
Exec={exec_line}
Hidden=false
X-GNOME-Autostart-enabled=true
"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    else:
        if path.exists():
            path.unlink()


def _is_autostart_linux() -> bool:
    return _desktop_file_path().exists()


# --- Public API ---

def set_autostart(enabled: bool) -> None:
    """Enable or disable autostart on the current platform."""
    if sys.platform == "darwin":
        _set_autostart_macos(enabled)
    elif sys.platform == "win32":
        _set_autostart_windows(enabled)
    else:
        _set_autostart_linux(enabled)


def is_autostart_enabled() -> bool:
    """Check if autostart is currently enabled."""
    if sys.platform == "darwin":
        return _is_autostart_macos()
    elif sys.platform == "win32":
        return _is_autostart_windows()
    else:
        return _is_autostart_linux()
