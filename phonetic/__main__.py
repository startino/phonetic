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


def _log(msg: str) -> None:
    """Append a diagnostic line to /tmp/phonetic_startup.log."""
    import time
    try:
        with open("/tmp/phonetic_startup.log", "a") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def main() -> None:
    _log("main() entered")
    _check_macos_installation()
    _log("installation check passed")

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
    _log(f"headless={headless}")
    if headless:
        print("Running in headless mode (no display detected or --headless flag)")

    _log("importing App")
    from .app import App
    _log("creating App")
    app = App(headless=headless)
    _log("calling app.run()")
    app.run()


def _get_version() -> str:
    from . import __version__
    return __version__


if __name__ == "__main__":
    main()
