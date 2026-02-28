"""Wayland setup helpers: DE detection, AI prompt generation, and startup notice."""

import os
import sys
from pathlib import Path


def _detect_de() -> str:
    """Detect the desktop environment from environment variables."""
    desktop = os.getenv("XDG_CURRENT_DESKTOP", "").strip()
    if desktop:
        return desktop
    session = os.getenv("DESKTOP_SESSION", "").strip()
    if session:
        return session
    return "unknown"


def _hotkey_human_readable(hotkey: str) -> str:
    """Convert pynput hotkey format to human-readable.

    '<ctrl>+<alt>+r' -> 'Ctrl+Alt+R'
    '<cmd>+<shift>+r' -> 'Cmd+Shift+R'
    """
    replacements = {
        "<ctrl>": "Ctrl",
        "<alt>": "Alt",
        "<shift>": "Shift",
        "<cmd>": "Cmd",
        "<super>": "Super",
    }
    parts = hotkey.split("+")
    result = []
    for part in parts:
        lower = part.lower().strip()
        if lower in replacements:
            result.append(replacements[lower])
        else:
            result.append(part.strip("<>").upper())
    return "+".join(result)


def _pid_file_path() -> Path:
    return Path.home() / ".cache" / "phonetic" / "pid"


def generate_setup_prompt(hotkey: str = "<ctrl>+<alt>+r") -> str:
    """Generate an AI-ready prompt for setting up Wayland hotkey binding."""
    de = _detect_de()
    human_hotkey = _hotkey_human_readable(hotkey)
    pid_path = _pid_file_path()

    return f"""\
I use Phonetic, a speech-to-text app, on Linux with Wayland ({de}).

Phonetic listens for SIGUSR1 to toggle recording. Its PID file is at:
  {pid_path}

I want to bind {human_hotkey} to toggle recording. Please give me step-by-step
instructions for my desktop environment ({de}) to create a custom keyboard
shortcut that runs:

  kill -USR1 $(cat {pid_path})

Include how to:
1. Open the keyboard shortcut settings
2. Add a new custom shortcut
3. Set the command and key binding
4. Test that it works
"""


def print_wayland_notice() -> None:
    """Print a concise Wayland startup notice."""
    pid_path = _pid_file_path()
    print(
        f"Wayland detected — global hotkeys use SIGUSR1 mode.\n"
        f"  Toggle recording:  kill -USR1 $(cat {pid_path})\n"
        f"  Setup guide:       phonetic --setup"
    )
