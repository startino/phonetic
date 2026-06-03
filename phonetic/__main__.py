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
        "--trigger",
        metavar="PROFILE",
        default=None,
        help="Tell the already-running Phonetic to record with PROFILE (its id "
             "OR its name), then exit. This is how global hotkeys work on "
             "Wayland: bind one DE/compositor shortcut per profile to "
             "`phonetic --trigger <name>`. Run `phonetic --list-profiles` to "
             "see what to bind.",
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="Print each configured profile's name, id, and hotkey, then exit. "
             "Use the name (or id) with --trigger to bind compositor shortcuts.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_get_version()}",
    )
    args = parser.parse_args()

    # --list-profiles is a thin client: read config + print, then exit.
    if args.list_profiles:
        _list_profiles()
        sys.exit(0)

    # --trigger is a thin client: send the profile ref to the running app's
    # control channel and exit. It does NOT start a second app instance.
    if args.trigger is not None:
        from .control import send_trigger
        ok = send_trigger(args.trigger)
        sys.exit(0 if ok else 1)

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


def _list_profiles() -> None:
    """Print configured profiles (name, id, hotkey) for binding compositor keys.

    On Wayland, each profile is triggered by a DE shortcut bound to
    `phonetic --trigger <name>`; this lists what to bind.
    """
    # Read profiles.json directly: listing must not depend on audio hardware
    # (load_config runs device detection, which fails on headless/device-less
    # boxes), and a thin client shouldn't spin up the full config pipeline.
    from .config import _load_profiles
    profiles = _load_profiles()
    if not profiles:
        print("No profiles configured. Open Settings (or edit profiles.json) "
              "to add one.")
        return
    print(f"{'NAME':<24} {'HOTKEY':<22} TRIGGER COMMAND")
    for p in profiles:
        # Prefer the name for the trigger command (readable); quote if spaced.
        ref = p.name if p.name and " " not in p.name else (f'"{p.name}"' if p.name else p.id)
        print(f"{(p.name or '(unnamed)'):<24} {(p.hotkey or '-'):<22} "
              f"phonetic --trigger {ref}")
    print("\nOn Wayland, bind a compositor/DE shortcut to each TRIGGER COMMAND.")
    print("On X11/macOS, the per-profile HOTKEY above works directly.")


if __name__ == "__main__":
    main()
