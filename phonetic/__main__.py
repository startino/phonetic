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
        "--version",
        action="version",
        version=f"%(prog)s {_get_version()}",
    )
    args = parser.parse_args()

    headless = args.headless or not has_display()
    if headless:
        print("Running in headless mode (no display detected or --headless flag)")

    from .app import App
    app = App(headless=headless)
    app.run()


def _get_version() -> str:
    from . import __version__
    return __version__


if __name__ == "__main__":
    main()
