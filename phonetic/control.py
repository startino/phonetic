"""Control channel: a named-pipe (FIFO) the running app drains for commands.

This is how a *profile id* reaches the running app from an external trigger —
the thing a Unix signal fundamentally cannot do (SIGUSR1 carries no payload).
On Wayland, where global hotkeys can't be grabbed, the user binds a DE keyboard
shortcut per profile to:

    phonetic --trigger <profile-id>

That CLI (see __main__.py) opens this FIFO and writes one line — the profile id.
The app's reader thread maps it to the matching profile and starts recording
with THAT profile. No default profile, no signal-count ceiling, race-free.

The channel is also platform-agnostic: `--trigger` works wherever the app runs,
not just Wayland, so the same mechanism powers any external automation.
"""

import os
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

from .log import log


def control_fifo_path() -> Path:
    """Path to the control FIFO. One per user; the single running app owns it."""
    return Path.home() / ".cache" / "phonetic" / "control"


def _supports_fifo() -> bool:
    return hasattr(os, "mkfifo") and not sys.platform.startswith("win")


class ControlChannel:
    """App-side reader: drains profile-id lines from the FIFO on a daemon thread.

    Each non-empty line read is handed to ``on_trigger(profile_id)``. The FIFO is
    opened O_RDWR so the reader never sees EOF when writers disconnect — it simply
    blocks for the next line, which keeps one long-lived thread instead of a
    reopen loop.
    """

    def __init__(self, on_trigger: Callable[[str], None]) -> None:
        self._on_trigger = on_trigger
        self._path = control_fifo_path()
        self._fd: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = False

    def start(self) -> bool:
        """Create the FIFO and start the reader thread. Returns True on success."""
        if not _supports_fifo():
            log("control: FIFO unsupported on this platform, --trigger disabled")
            return False
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Recreate the FIFO fresh each run: a stale node from a crashed
            # instance is harmless to replace, and guarantees correct type/perms.
            if self._path.exists():
                try:
                    self._path.unlink()
                except OSError:
                    pass
            os.mkfifo(self._path, 0o600)
            # O_RDWR keeps the pipe permanently open from our side (no EOF storms).
            self._fd = os.open(self._path, os.O_RDWR | os.O_NONBLOCK)
        except OSError as e:
            log(f"control: could not create FIFO at {self._path}: {e}")
            self._fd = None
            return False

        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()
        log(f"control: channel ready at {self._path}")
        return True

    def _reader_loop(self) -> None:
        import select

        buf = b""
        while not self._stop:
            # Snapshot the fd ONCE per iteration. stop() nulls self._fd on
            # another thread, so reading it repeatedly here races: select/read
            # could see a live fd and then os.read(None) raises TypeError. Bind
            # it locally and bail if shutdown already closed it.
            fd = self._fd
            if fd is None:
                break
            try:
                # Block until readable (or 1s timeout to re-check _stop).
                rlist, _, _ = select.select([fd], [], [], 1.0)
                if not rlist:
                    continue
                chunk = os.read(fd, 4096)
                if not chunk:
                    continue
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    profile_id = line.decode("utf-8", "replace").strip()
                    if profile_id:
                        log(f"control: received trigger for profile_id={profile_id!r}")
                        try:
                            self._on_trigger(profile_id)
                        except Exception as e:
                            log(f"control: on_trigger raised: {e}")
            except (OSError, ValueError) as e:
                if self._stop:
                    break
                log(f"control: reader error: {e}")

    def stop(self) -> None:
        self._stop = True
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        try:
            if self._path.exists():
                self._path.unlink()
        except OSError:
            pass


def send_trigger(profile_id: str) -> bool:
    """Write ``profile_id`` to the running app's control FIFO.

    Returns True if delivered, False if the app isn't running (no reader) or the
    platform lacks FIFOs. Used by `phonetic --trigger <id>`.
    """
    if not _supports_fifo():
        print("Control channel is not supported on this platform.", file=sys.stderr)
        return False

    path = control_fifo_path()
    if not path.exists():
        print("Phonetic does not appear to be running (no control channel).",
              file=sys.stderr)
        return False

    try:
        # Non-blocking open-for-write fails fast with ENXIO if no reader is
        # attached — exactly the "app not running" signal we want.
        fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
    except OSError as e:
        print(f"Phonetic is not listening on the control channel: {e}",
              file=sys.stderr)
        return False

    try:
        os.write(fd, (profile_id.strip() + "\n").encode("utf-8"))
        return True
    except OSError as e:
        print(f"Failed to send trigger: {e}", file=sys.stderr)
        return False
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
