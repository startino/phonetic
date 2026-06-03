"""Control-channel tests: the FIFO that carries a profile id from
`phonetic --trigger <id>` to the running app (the Wayland per-profile path)."""
import os
import sys
import threading
import time

import pytest

from phonetic import control


pytestmark = pytest.mark.skipif(
    not hasattr(os, "mkfifo") or sys.platform.startswith("win"),
    reason="FIFO control channel requires POSIX mkfifo",
)


@pytest.fixture
def isolated_fifo(tmp_path, monkeypatch):
    fifo = tmp_path / "control"
    monkeypatch.setattr(control, "control_fifo_path", lambda: fifo)
    yield fifo


def test_send_without_running_app_fails_cleanly(isolated_fifo, capsys):
    """No reader running => send_trigger returns False, doesn't hang/raise."""
    assert control.send_trigger("any-id") is False


def test_trigger_roundtrip_delivers_profile_id(isolated_fifo):
    """A started channel delivers the exact profile id written by send_trigger."""
    received = []
    done = threading.Event()

    def on_trigger(pid):
        received.append(pid)
        done.set()

    chan = control.ControlChannel(on_trigger)
    assert chan.start() is True
    try:
        # Give the reader thread a beat to enter its select loop.
        time.sleep(0.1)
        assert control.send_trigger("work-id") is True
        assert done.wait(timeout=2.0), "trigger was not delivered"
        assert received == ["work-id"]
    finally:
        chan.stop()


def test_multiple_triggers_each_deliver(isolated_fifo):
    received = []
    lock = threading.Event()

    def on_trigger(pid):
        received.append(pid)
        if len(received) >= 3:
            lock.set()

    chan = control.ControlChannel(on_trigger)
    assert chan.start() is True
    try:
        time.sleep(0.1)
        for pid in ("a", "b", "c"):
            assert control.send_trigger(pid) is True
            time.sleep(0.02)
        assert lock.wait(timeout=2.0)
        assert received == ["a", "b", "c"]
    finally:
        chan.stop()


def test_stop_removes_fifo(isolated_fifo):
    chan = control.ControlChannel(lambda pid: None)
    assert chan.start() is True
    assert isolated_fifo.exists()
    chan.stop()
    assert not isolated_fifo.exists()
