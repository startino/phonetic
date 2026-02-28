"""Background update checker — queries GitHub Releases API."""

from __future__ import annotations

from typing import Optional

import httpx
from packaging.version import parse as parse_version

_RELEASES_URL = "https://api.github.com/repos/startino/phonetic/releases/latest"
_TIMEOUT = 5


def check_for_update(current_version: str) -> Optional[tuple[bool, str, str]]:
    """Return (True, latest_version, html_url) if a newer release exists.

    Returns None on error or when already up-to-date.
    Never raises — all exceptions are swallowed so the app keeps running.
    """
    try:
        resp = httpx.get(
            _RELEASES_URL,
            timeout=_TIMEOUT,
            headers={"Accept": "application/vnd.github+json"},
        )
        resp.raise_for_status()
        data = resp.json()

        tag = data.get("tag_name", "")
        latest = tag.lstrip("v")
        html_url = data.get("html_url", "")

        if parse_version(latest) > parse_version(current_version):
            return (True, latest, html_url)
    except Exception:
        pass

    return None
