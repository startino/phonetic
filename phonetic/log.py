import time

# Verbose diagnostic logging. Defaults ON: bundled builds have no visible
# stderr, so these logs are the primary way to diagnose install/runtime issues
# (see CLAUDE.md "Never remove logs"). settings.json `verbose: false` is the
# opt-out for users who want a quiet log; PHONETIC_VERBOSE=0 forces quiet too.
import os

_env = os.getenv("PHONETIC_VERBOSE")
_verbose: bool = True if _env is None else _env.strip().lower() not in {"0", "false", "no", ""}


def set_verbose(value: bool) -> None:
    """Enable/disable verbose diagnostic logging (from settings.json).

    An explicit PHONETIC_VERBOSE env var always wins over the settings value.
    """
    global _verbose
    if os.getenv("PHONETIC_VERBOSE") is not None:
        return  # env override is authoritative
    _verbose = bool(value)


def log(msg: str) -> None:
    """Append a diagnostic line to /tmp/phonetic_startup.log when verbose."""
    if not _verbose:
        return
    try:
        with open("/tmp/phonetic_startup.log", "a") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass
