import argparse
import sys

from .platform_utils import has_display, is_frozen


def _check_macos_installation() -> None:
    """On macOS, abort early if launched from a DMG or translocated path."""
    if sys.platform != "darwin" or not is_frozen():
        return
    exe = sys.executable
    if "/AppTranslocation/" in exe or exe.startswith("/Volumes/"):
        # Temporarily become a foreground app so the dialog is visible
        # (LSUIElement hides us from the dock, making windows unfocusable)
        from AppKit import NSApplication, NSApplicationActivationPolicyRegular
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyRegular)

        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Phonetic — Installation Required",
            "Phonetic is running from a disk image.\n\n"
            "Please drag Phonetic to your Applications folder first, "
            "then launch it from there.",
        )
        root.destroy()
        sys.exit(0)


def main() -> None:
    _check_macos_installation()

    parser = argparse.ArgumentParser(
        prog="phonetic",
        description="Hotkey-based speech-to-text via multimodal LLM",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless mode (no GUI, no tray icon)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_get_version()}",
    )
    args = parser.parse_args()

    headless = args.headless or not has_display()
    if headless:
        print("Running in headless mode (no display detected or --headless flag)")

    from .app import App
    app = App(headless=headless)
    app.run()


def _get_version() -> str:
    from . import __version__
    return __version__


if __name__ == "__main__":
    main()
