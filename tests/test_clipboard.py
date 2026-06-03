"""Tests for clipboard env discovery (Wayland socket fallback).

A headless systemd service doesn't inherit WAYLAND_DISPLAY; _wayland_env must
discover the live socket so wl-copy can connect. Regression guard for the
"Transcription ready (clipboard unavailable)" failure on the deployed service.
"""
import os
import tempfile
from unittest import mock

from phonetic.clipboard import _wayland_env


def test_wayland_env_passes_through_existing_display():
    with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-1"}, clear=True):
        assert _wayland_env()["WAYLAND_DISPLAY"] == "wayland-1"


def test_wayland_env_discovers_socket_when_unset():
    d = tempfile.mkdtemp()
    open(os.path.join(d, "wayland-1"), "w").close()
    with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": d}, clear=True):
        assert _wayland_env().get("WAYLAND_DISPLAY") == "wayland-1"


def test_wayland_env_absent_when_no_socket():
    d = tempfile.mkdtemp()
    with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": d}, clear=True):
        assert "WAYLAND_DISPLAY" not in _wayland_env()
