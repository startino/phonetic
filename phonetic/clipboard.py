import os
import shutil
import subprocess
import sys

from .platform_utils import _is_wayland


def _wayland_env() -> dict:
    """Environment for wl-copy that points at the live Wayland socket.

    A headless systemd **user** service does not inherit ``WAYLAND_DISPLAY``
    from the compositor session (systemd only exports it if the compositor runs
    ``systemctl --user import-environment WAYLAND_DISPLAY``). Without it,
    ``wl-copy`` falls back to ``wayland-0`` and fails when the compositor uses
    ``wayland-1`` (common with Hyprland), so the clipboard "works in-session but
    not as the service". We discover the actual socket in ``XDG_RUNTIME_DIR``
    and set ``WAYLAND_DISPLAY`` ourselves so wl-copy connects regardless.
    """
    env = dict(os.environ)
    if env.get("WAYLAND_DISPLAY"):
        return env
    runtime = env.get("XDG_RUNTIME_DIR")
    if not runtime:
        runtime = f"/run/user/{os.getuid()}"
        if os.path.isdir(runtime):
            env["XDG_RUNTIME_DIR"] = runtime
    if runtime:
        for name in ("wayland-0", "wayland-1", "wayland-2"):
            if os.path.exists(os.path.join(runtime, name)):
                env["WAYLAND_DISPLAY"] = name
                break
    return env


def _run_clip(cmd: list[str], text: str, env: dict | None = None) -> None:
    """Run a clipboard tool, raising a clear, actionable error on failure.

    Note: wl-copy/xclip fork a daemon that holds the selection and keeps the
    inherited fds open, so we deliberately do NOT pipe their output (that would
    block until timeout). Their own stderr goes to the journal; we add a
    precise message here. check=True surfaces a connect failure (non-zero exit
    before the fork)."""
    exe = cmd[0]
    search_path = (env or os.environ).get("PATH")
    if shutil.which(exe, path=search_path) is None:
        raise RuntimeError(
            f"{exe} not on PATH. On NixOS the phonetic package wraps "
            f"wl-clipboard/xclip; otherwise install it. PATH={search_path!r}"
        )
    try:
        subprocess.run(
            cmd,
            input=text.encode("utf-8"),
            check=True,
            timeout=5,
            env=env,
        )
    except subprocess.CalledProcessError as e:
        wd = (env or os.environ).get("WAYLAND_DISPLAY")
        raise RuntimeError(
            f"{exe} exited {e.returncode} (see journal for its stderr; "
            f"WAYLAND_DISPLAY={wd!r}). Likely cannot reach the compositor."
        ) from e


def copy_to_clipboard(text: str) -> None:
    """Copy text to system clipboard using native tools."""
    if sys.platform.startswith("linux"):
        if _is_wayland():
            _run_clip(["wl-copy"], text, env=_wayland_env())
        else:
            _run_clip(["xclip", "-selection", "clipboard"], text)
    else:
        import pyperclip
        pyperclip.copy(text)
