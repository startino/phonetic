"""`phonetic doctor` — a read-only, UI-free health probe.

Reports, without mutating anything and without importing any UI module:

- **Microphone permission** (macOS; "not applicable" elsewhere).
- **Hotkey backend** — which ``HotkeyManager`` the platform WOULD select
  (Carbon / pynput / Wayland-SIGUSR1), determined the same way the factory does,
  but WITHOUT constructing or starting a listener.
- **Clipboard reachability** — whether the platform's clipboard tool is present
  (wl-copy / xclip on Linux, pyperclip elsewhere). Does not write to the
  clipboard.
- **Daemon status — HONESTLY** (scope risk #8). NEVER ``path.exists()`` on the
  FIFO: ``control.py`` recreates a stale FIFO from a crashed instance, so mere
  existence lies. The only portable honest signal is the FIFO non-blocking probe
  (``O_WRONLY | O_NONBLOCK`` raises ``ENXIO`` when no reader is attached). On
  Linux the pidfile (Linux-only, atexit-cleaned) corroborates via ``kill(pid,
  0)``. macOS/Windows have NO pidfile and must not claim one. Output is an honest
  three-state: running / not running / unknown-on-this-platform.
"""

import errno
import os
import sys

from .log import log


def _check_mic() -> tuple[str, str]:
    """(state, detail) for microphone permission. Read-only."""
    from .mic_permission import microphone_status
    status = microphone_status()
    detail = {
        "authorized": "authorized",
        "denied": "DENIED -- run `phonetic grant-mic` or enable it in System Settings",
        "restricted": "restricted by policy",
        "not_determined": "not yet requested -- run `phonetic grant-mic`",
        "unavailable": "could not query AVFoundation",
        "not_applicable": "not applicable on this platform",
    }.get(status, status)
    return status, detail


def _check_hotkey_backend() -> tuple[str, str]:
    """(backend, detail) for the hotkey manager the platform would select.

    Mirrors the HotkeyManager factory's branch logic without building a manager
    or starting any listener (read-only)."""
    if sys.platform == "darwin":
        return "carbon", ("Carbon RegisterEventHotKey (no permissions needed); "
                          "per-profile global hotkeys supported")
    if sys.platform.startswith("linux"):
        from .platform_utils import _is_wayland
        if _is_wayland():
            return "wayland-signal", (
                "Wayland session: global hotkeys cannot be grabbed; bind a "
                "compositor shortcut per profile to `phonetic --trigger <name>`")
    from .hotkeys import _load_pynput
    if _load_pynput() is None:
        return "signal-only", (
            "pynput unavailable: SIGUSR1 / --trigger only, no per-profile global "
            "hotkeys")
    return "pynput", "pynput global hotkeys (X11 / Windows)"


def _check_clipboard() -> tuple[str, str]:
    """(state, detail) for clipboard reachability. Read-only (no copy)."""
    if sys.platform.startswith("linux"):
        import shutil
        from .platform_utils import _is_wayland
        tool = "wl-copy" if _is_wayland() else "xclip"
        if shutil.which(tool) is not None:
            return "ok", f"{tool} found on PATH"
        return "missing", (
            f"{tool} not on PATH -- install wl-clipboard (Wayland) or xclip "
            f"(X11); on NixOS the phonetic package wraps them")
    # macOS / Windows use pyperclip.
    try:
        import pyperclip  # noqa: F401
        return "ok", "pyperclip available"
    except Exception as exc:
        return "missing", f"pyperclip unavailable: {exc}"


def _check_daemon() -> tuple[str, str]:
    """(state, detail) for daemon liveness. HONEST: probes the FIFO reader, never
    trusts file presence. state is one of 'running' / 'not-running' / 'unknown'."""
    from .control import control_fifo_path, _supports_fifo

    if not _supports_fifo():
        # No FIFO on this platform: we cannot honestly probe liveness here.
        return "unknown", ("no control FIFO on this platform -- cannot probe "
                           "the running daemon")

    path = control_fifo_path()
    if not path.exists():
        # No FIFO node at all => the daemon has never created its channel this
        # boot (or cleaned it up on exit). This is a genuine 'not running' --
        # but we still corroborate on Linux below before concluding.
        fifo_state = "not-running"
        fifo_detail = "no control FIFO present"
    else:
        # The honest probe: open the FIFO non-blocking for write. ENXIO means the
        # node exists but NO reader is attached -- a stale FIFO from a crashed
        # instance. A successful open means a live reader (the daemon) is there.
        try:
            fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
            os.close(fd)
            return "running", f"live reader on the control FIFO ({path})"
        except OSError as e:
            if e.errno == errno.ENXIO:
                fifo_state = "not-running"
                fifo_detail = ("control FIFO exists but no reader is attached "
                               "(stale node from a crashed instance)")
            else:
                fifo_state = "unknown"
                fifo_detail = f"could not probe the control FIFO: {e}"

    # Linux-only corroboration via the pidfile (Linux-only, atexit-cleaned).
    # macOS/Windows have no pidfile and must not claim one.
    if sys.platform.startswith("linux"):
        from pathlib import Path
        pidfile = Path.home() / ".cache" / "phonetic" / "pid"
        if pidfile.is_file():
            try:
                pid = int(pidfile.read_text(encoding="utf-8").strip())
                os.kill(pid, 0)  # signal 0 = liveness check, no signal sent
                return "running", f"pid {pid} alive (pidfile); {fifo_detail}"
            except (ValueError, ProcessLookupError):
                return "not-running", f"stale pidfile; {fifo_detail}"
            except PermissionError:
                # Process exists but owned by another user -- it is alive.
                return "running", f"pidfile pid alive (EPERM); {fifo_detail}"
            except OSError:
                pass

    return fifo_state, fifo_detail


def run_doctor() -> int:
    """Print the diagnostic report. Returns a process exit code: 0 if nothing is
    clearly broken, 1 if a hard problem (missing clipboard tool, denied mic on
    macOS) is detected. Read-only; imports no UI."""
    log("doctor: running diagnostic probe")
    from . import __version__

    print(f"Phonetic {__version__} -- doctor")
    print(f"  platform: {sys.platform}")

    mic_state, mic_detail = _check_mic()
    hk_backend, hk_detail = _check_hotkey_backend()
    clip_state, clip_detail = _check_clipboard()
    daemon_state, daemon_detail = _check_daemon()

    print(f"  microphone:  {mic_state:<14} {mic_detail}")
    print(f"  hotkeys:     {hk_backend:<14} {hk_detail}")
    print(f"  clipboard:   {clip_state:<14} {clip_detail}")
    print(f"  daemon:      {daemon_state:<14} {daemon_detail}")

    log(f"doctor: mic={mic_state} hotkeys={hk_backend} clipboard={clip_state} "
        f"daemon={daemon_state}")

    problems = []
    if clip_state == "missing":
        problems.append("clipboard tool missing")
    if sys.platform == "darwin" and mic_state in ("denied", "restricted"):
        problems.append("microphone access not granted")

    if problems:
        print(f"\nProblems detected: {', '.join(problems)}.")
        return 1
    print("\nNo blocking problems detected.")
    return 0
