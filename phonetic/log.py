import time


def log(msg: str) -> None:
    """Append a diagnostic line to /tmp/phonetic_startup.log."""
    try:
        with open("/tmp/phonetic_startup.log", "a") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass
