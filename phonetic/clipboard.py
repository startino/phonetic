import subprocess
import sys

from .platform_utils import _is_wayland


def copy_to_clipboard(text: str) -> None:
    """Copy text to system clipboard using native tools."""
    if sys.platform.startswith("linux"):
        if _is_wayland():
            subprocess.run(
                ["wl-copy"],
                input=text.encode("utf-8"),
                check=True,
                timeout=5,
            )
        else:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text.encode("utf-8"),
                check=True,
                timeout=5,
            )
    else:
        import pyperclip
        pyperclip.copy(text)
