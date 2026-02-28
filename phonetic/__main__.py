import argparse
import sys

from .platform_utils import has_display


def main() -> None:
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
        "--setup",
        action="store_true",
        help="Print an AI-ready prompt for setting up Wayland hotkey binding",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_get_version()}",
    )
    args = parser.parse_args()

    if args.setup:
        _print_setup()
        return

    headless = args.headless or not has_display()
    if headless:
        print("Running in headless mode (no display detected or --headless flag)")

    from .app import App
    app = App(headless=headless)
    app.run()


def _print_setup() -> None:
    """Load config for hotkey preference, print AI setup prompt, exit."""
    from .config import load_config
    from .setup_prompt import generate_setup_prompt

    try:
        cfg = load_config(require_key=False)
    except Exception:
        cfg = None

    default_hotkey = "<cmd>+<shift>+r" if sys.platform == "darwin" else "<ctrl>+<alt>+r"
    hotkey = cfg.hotkey if cfg else default_hotkey

    print(generate_setup_prompt(hotkey))


def _get_version() -> str:
    from . import __version__
    return __version__


if __name__ == "__main__":
    main()
