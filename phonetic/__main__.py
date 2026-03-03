import argparse
import os
import sys

from .platform_utils import has_display, is_frozen


def _check_macos_installation() -> None:
    """On macOS, auto-install to ~/Applications if launched from a DMG or translocated path."""
    if sys.platform != "darwin" or not is_frozen():
        return
    exe = sys.executable
    if "/AppTranslocation/" not in exe and not exe.startswith("/Volumes/"):
        return

    import shutil
    import subprocess

    # Tk must initialise its own NSApplication *before* we touch AppKit,
    # otherwise Tk's internal GetRGBA crashes with "unrecognized selector".
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()

    # Now make the app a foreground app so the dialog is visible
    # (LSUIElement hides us from the dock, making windows unfocusable)
    from AppKit import NSApplication, NSApplicationActivationPolicyRegular
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyRegular)
    root.lift()
    root.attributes("-topmost", True)

    # Walk up from the executable to find the .app bundle
    app_bundle = exe
    while app_bundle and not app_bundle.endswith(".app"):
        app_bundle = os.path.dirname(app_bundle)

    if not app_bundle:
        messagebox.showerror("Phonetic", "Could not determine app bundle path.")
        root.destroy()
        sys.exit(1)

    dest_dir = os.path.expanduser("~/Applications")
    dest_app = os.path.join(dest_dir, "Phonetic.app")

    result = messagebox.askyesno(
        "Install Phonetic",
        "Phonetic needs to be installed before it can run.\n\n"
        f"Install to {dest_dir}?",
    )

    if not result:
        root.destroy()
        sys.exit(0)

    try:
        os.makedirs(dest_dir, exist_ok=True)
        if os.path.exists(dest_app):
            shutil.rmtree(dest_app)
        shutil.copytree(app_bundle, dest_app)
        subprocess.Popen(["open", dest_app])
    except Exception as e:
        messagebox.showerror("Phonetic", f"Installation failed:\n{e}")
    root.destroy()
    sys.exit(0)


def main() -> None:
    from .log import log as _log
    import platform
    import threading

    _log("=" * 60)
    _log("main() entered — NEW SESSION")
    _log(f"  PID={os.getpid()}")
    _log(f"  Python={sys.version}")
    _log(f"  executable={sys.executable}")
    _log(f"  platform={sys.platform}")
    _log(f"  frozen={is_frozen()}")
    _log(f"  macOS version={platform.mac_ver()[0] if sys.platform == 'darwin' else 'N/A'}")
    _log(f"  thread={threading.current_thread().name} (id={threading.get_ident()})")
    if is_frozen():
        _log(f"  bundle dir={os.path.dirname(os.path.dirname(sys.executable))}")
    _log("=" * 60)

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
