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

    parser = _build_parser()
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Thin-client dispatch. EVERY verb that only reads/mutates config or
    # probes state resolves and sys.exit()s HERE, BEFORE `from .app import App`.
    # This pre-App-import block is what keeps the CLI surface UI-free AND
    # audio-free: a `config`/`doctor`/`grant-mic`/`--list-profiles`/`--trigger`
    # invocation never imports app.py, the tray, or any UI module, and never
    # spins up device detection. (Load-bearing for the areliant property.)
    # ------------------------------------------------------------------

    command = getattr(args, "command", None)

    # `phonetic config ...` subverbs.
    if command == "config":
        sys.exit(_run_config_command(args))

    # `phonetic grant-mic` — macOS first-run mic permission (no-op elsewhere).
    if command == "grant-mic":
        _log("cli: grant-mic")
        from .mic_permission import grant_microphone
        sys.exit(0 if grant_microphone() else 1)

    # `phonetic doctor` — read-only health probe.
    if command == "doctor":
        _log("cli: doctor")
        from .doctor import run_doctor
        sys.exit(run_doctor())

    # --list-profiles is a thin client (and a back-compat ALIAS of
    # `config list`): read config + print, then exit. Documented Wayland setup
    # instructs `phonetic --list-profiles`, so it must keep working.
    if getattr(args, "list_profiles", False):
        _log("cli: --list-profiles (alias of `config list`)")
        _list_profiles()
        sys.exit(0)

    # --trigger is a thin client: send the profile ref to the running app's
    # control channel and exit. It does NOT start a second app instance.
    if getattr(args, "trigger", None) is not None:
        _log(f"cli: --trigger {args.trigger!r}")
        from .control import send_trigger
        ok = send_trigger(args.trigger)
        sys.exit(0 if ok else 1)

    # No subcommand and no thin flag: fall through to the default daemon/GUI
    # path. `dest="command"` is non-required, so plain `phonetic` lands here
    # with the current default UX (DECISION 4).
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


def _build_parser() -> "argparse.ArgumentParser":
    """Build the argparse parser: flat back-compat flags + `config` subverbs.

    The top-level flat flags (--headless / --trigger / --list-profiles /
    --version) are PRESERVED for back-compat. `config` is a subcommand group
    (list / add-profile / edit / remove / path). `dest="command"` is NOT
    required, so plain `phonetic` (no subcommand) falls through to the default
    daemon/GUI path.
    """
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
             "`phonetic --trigger <name>`. Run `phonetic config list` to "
             "see what to bind.",
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="Alias of `phonetic config list`: print each configured profile's "
             "name and hotkey, then exit.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_get_version()}",
    )

    sub = parser.add_subparsers(dest="command")

    # phonetic config ...
    config = sub.add_parser(
        "config",
        help="Read or change Phonetic's configuration without opening any UI.",
        description="Configure Phonetic from the command line. Every operation "
                    "targets the same files the daemon reads.",
    )
    config_sub = config.add_subparsers(dest="config_command")

    config_sub.add_parser(
        "list", help="List configured profiles (name, hotkey, trigger command).")

    p_add = config_sub.add_parser(
        "add-profile", help="Add a new profile.")
    p_add.add_argument("name", help="Profile name (its identity).")
    _add_profile_field_args(p_add)

    p_edit = config_sub.add_parser(
        "edit", help="Edit fields of an existing profile (by name).")
    p_edit.add_argument("name", help="Name of the profile to edit.")
    p_edit.add_argument("--name", dest="new_name", metavar="NEW_NAME",
                        help="Rename the profile.")
    _add_profile_field_args(p_edit)

    p_remove = config_sub.add_parser(
        "remove", help="Remove a profile by name.")
    p_remove.add_argument("name", help="Name of the profile to remove.")

    config_sub.add_parser(
        "path", help="Print the resolved config file paths (secrets + settings/"
                     "profiles), so you know exactly which files are in use.")

    p_key = config_sub.add_parser(
        "set-key", help="Set the OpenRouter API key in the resolved .env.")
    p_key.add_argument("api_key", help="The OpenRouter API key to store.")

    p_toggle = config_sub.add_parser(
        "set", help="Set a settings.json toggle (notify/verbose/auto_start).")
    p_toggle.add_argument("toggle", choices=["notify", "verbose", "auto_start"],
                         help="Which toggle to set.")
    p_toggle.add_argument("value", choices=["on", "off"], help="on or off.")

    # phonetic grant-mic
    sub.add_parser(
        "grant-mic",
        help="Request macOS microphone permission (no-op on other platforms).",
        description="Trigger the macOS first-run microphone permission dialog. "
                    "Headless: prints status, opens no window.")

    # phonetic doctor
    sub.add_parser(
        "doctor",
        help="Print a read-only health report (mic / hotkeys / clipboard / "
             "daemon).",
        description="Diagnose Phonetic's environment without changing anything.")

    return parser


def _add_profile_field_args(p: "argparse.ArgumentParser") -> None:
    """Add the shared profile-field options (hotkey/model/.../prompt) to a
    config subparser. Used by both add-profile and edit."""
    p.add_argument("--hotkey", help="Hotkey, e.g. '<ctrl>+<alt>+r'.")
    p.add_argument("--model", help="Single-call / fallback-format model id.")
    p.add_argument("--asr-model", dest="asr_model",
                   help="ASR-only model for the two-stage path (optional).")
    p.add_argument("--format-model", dest="format_model",
                   help="Formatting model for the two-stage path (optional).")
    p.add_argument("--system-prompt", dest="system_prompt",
                   help="System prompt shaping this profile's output.")


def _run_config_command(args) -> int:
    """Dispatch `phonetic config <subcommand>`. Thin client over config_ops;
    imports no UI, touches no audio. Returns a process exit code."""
    from .log import log as _log
    sub = getattr(args, "config_command", None)
    _log(f"cli: config {sub}")

    # `config` with no subcommand: behave like `config list` (most useful default).
    if sub in (None, "list"):
        _list_profiles()
        return 0

    import phonetic.config_ops as ops

    if sub == "add-profile":
        stored = ops.add_profile(
            name=args.name,
            hotkey=args.hotkey or "",
            model=args.model or "",
            asr_model=args.asr_model or "",
            format_model=args.format_model or "",
            system_prompt=args.system_prompt or "",
        )
        print(f"Added profile {stored.name!r}"
              + (f" (hotkey {stored.hotkey})" if stored.hotkey else " (no hotkey)"))
        return 0

    if sub == "edit":
        fields: dict[str, str] = {}
        if getattr(args, "new_name", None) is not None:
            fields["name"] = args.new_name
        for key in ("hotkey", "model", "asr_model", "format_model",
                    "system_prompt"):
            val = getattr(args, key, None)
            if val is not None:
                fields[key] = val
        if not fields:
            print("Nothing to edit -- pass at least one field "
                  "(--hotkey/--model/--name/...).", file=sys.stderr)
            return 1
        try:
            stored = ops.edit_profile(args.name, fields)
        except KeyError:
            print(f"No profile named {args.name!r}. Run `phonetic config list`.",
                  file=sys.stderr)
            return 1
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        print(f"Updated profile {stored.name!r}.")
        return 0

    if sub == "remove":
        if ops.remove_profile(args.name):
            print(f"Removed profile {args.name!r}.")
            return 0
        print(f"No profile named {args.name!r}. Run `phonetic config list`.",
              file=sys.stderr)
        return 1

    if sub == "path":
        # Print BOTH resolved targets so the secrets/settings asymmetry is
        # VISIBLE, not a silent trap. Aligned columns so the paths line up.
        for label, value in (
            ("secrets (.env):", ops.secrets_path()),
            ("settings (settings.json):", ops.settings_path()),
            ("profiles (profiles.json):", ops.profiles_path()),
            ("config dir:", ops.config_dir()),
        ):
            print(f"{label:<26}{value}")
        return 0

    if sub == "set-key":
        path = ops.set_api_key(args.api_key)
        print(f"Wrote OpenRouter API key to {path}")
        return 0

    if sub == "set":
        ops.set_toggle(args.toggle, args.value == "on")
        print(f"Set {args.toggle} = {args.value}")
        return 0

    print(f"Unknown config subcommand: {sub}", file=sys.stderr)
    return 2


def _get_version() -> str:
    from . import __version__
    return __version__


def _list_profiles() -> None:
    """Print configured profiles (name, hotkey, trigger command) for binding
    compositor keys.

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
