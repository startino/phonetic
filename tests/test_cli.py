"""CLI verb tests: `phonetic config / grant-mic / doctor` + back-compat flags.

These drive the argparse dispatch helpers directly (not a subprocess), under the
conftest isolated_config fixture, so config writes land in a tmp dir. They assert
the thin verbs are UI-free and audio-free (they must resolve and exit before
`from .app import App`), which is the same property the areliant test enforces.
"""
import sys
import types

import pytest


@pytest.fixture(autouse=True)
def _stub_native_deps(monkeypatch):
    """Stub native-lib-backed core deps so importing phonetic.__main__ and the
    verb modules works in a headless CI box (no PortAudio / libsndfile)."""
    for name in ("sounddevice", "soundfile"):
        if name not in sys.modules:
            monkeypatch.setitem(sys.modules, name, types.ModuleType(name))


def _parse(argv):
    from phonetic.__main__ import _build_parser
    return _build_parser().parse_args(argv)


# --- config list / add / edit / remove round-trip -----------------------------


def test_config_add_list_edit_remove(isolated_config, capsys):
    from phonetic.__main__ import _run_config_command
    import phonetic.config_ops as ops

    assert _run_config_command(_parse(["config", "list"])) == 0
    assert "No profiles configured" in capsys.readouterr().out

    rc = _run_config_command(
        _parse(["config", "add-profile", "Work", "--hotkey", "<ctrl>+<alt>+w",
                "--model", "test/m"]))
    assert rc == 0
    assert "Added profile 'Work'" in capsys.readouterr().out
    assert [p.name for p in ops.list_profiles()] == ["Work"]

    rc = _run_config_command(
        _parse(["config", "edit", "Work", "--name", "Email", "--model", "test/m2"]))
    assert rc == 0
    assert "Updated profile 'Email'" in capsys.readouterr().out
    names = [p.name for p in ops.list_profiles()]
    assert names == ["Email"]
    assert ops.list_profiles()[0].model == "test/m2"

    rc = _run_config_command(_parse(["config", "remove", "Email"]))
    assert rc == 0
    assert ops.list_profiles() == []  # remove-to-zero is legal (no default).


def test_config_edit_missing_profile_errors(isolated_config, capsys):
    from phonetic.__main__ import _run_config_command
    rc = _run_config_command(_parse(["config", "edit", "Ghost", "--model", "m"]))
    assert rc == 1
    assert "No profile named 'Ghost'" in capsys.readouterr().err


def test_config_edit_requires_a_field(isolated_config, capsys):
    from phonetic.__main__ import _run_config_command
    import phonetic.config_ops as ops
    ops.add_profile("Solo")
    rc = _run_config_command(_parse(["config", "edit", "Solo"]))
    assert rc == 1
    assert "Nothing to edit" in capsys.readouterr().err


def test_config_remove_missing_errors(isolated_config, capsys):
    from phonetic.__main__ import _run_config_command
    rc = _run_config_command(_parse(["config", "remove", "Nope"]))
    assert rc == 1
    assert "No profile named 'Nope'" in capsys.readouterr().err


# --- config set-key / set toggles --------------------------------------------


def test_config_set_key_writes_resolved_env(isolated_config, capsys):
    from phonetic.__main__ import _run_config_command
    import phonetic.config_ops as ops
    rc = _run_config_command(_parse(["config", "set-key", "sk-or-test"]))
    assert rc == 0
    path = ops.secrets_path()
    assert path.is_file()
    assert "sk-or-test" in path.read_text(encoding="utf-8")


def test_config_set_toggle(isolated_config):
    from phonetic.__main__ import _run_config_command
    import phonetic.config_ops as ops
    assert _run_config_command(_parse(["config", "set", "notify", "off"])) == 0
    assert ops.get_settings()["notify"] is False
    assert _run_config_command(_parse(["config", "set", "notify", "on"])) == 0
    assert ops.get_settings()["notify"] is True


# --- config path: prints BOTH resolved targets (asymmetry visible) ------------


def test_config_path_prints_both_targets(isolated_config, capsys):
    from phonetic.__main__ import _run_config_command
    assert _run_config_command(_parse(["config", "path"])) == 0
    out = capsys.readouterr().out
    assert "secrets" in out and ".env" in out
    assert "settings.json" in out
    assert "profiles.json" in out


# --- doctor: read-only, honest three-state daemon probe -----------------------


def test_doctor_runs_readonly(isolated_config, capsys):
    from phonetic.doctor import run_doctor
    rc = run_doctor()  # 0 or 1 (1 if clipboard tool missing); never raises.
    assert rc in (0, 1)
    out = capsys.readouterr().out
    assert "microphone" in out and "hotkeys" in out
    assert "clipboard" in out and "daemon" in out


def test_doctor_daemon_state_is_honest_not_running(isolated_config):
    """With no live reader, doctor reports the daemon as not-running / unknown --
    it must NOT trust mere FIFO presence (a stale node would lie)."""
    from phonetic import doctor

    state, _ = doctor._check_daemon()
    # On a clean box with no daemon, the only honest answers are not-running or
    # unknown (never 'running').
    assert state in ("not-running", "unknown")


# --- grant-mic: non-macOS clean no-op ----------------------------------------


def test_grant_mic_noop_off_macos(monkeypatch, capsys):
    from phonetic.mic_permission import grant_microphone
    monkeypatch.setattr(sys, "platform", "linux")
    assert grant_microphone() is True
    assert "macOS only" in capsys.readouterr().out


def test_microphone_status_not_applicable_off_macos(monkeypatch):
    from phonetic.mic_permission import microphone_status
    monkeypatch.setattr(sys, "platform", "linux")
    assert microphone_status() == "not_applicable"


# --- thin verbs do NOT import app or any UI module ----------------------------


def test_config_dispatch_imports_no_app_or_ui(isolated_config):
    """The whole point of the pre-App-import dispatch: a config verb must not pull
    in phonetic.app, the tray, or any UI module."""
    from phonetic.__main__ import _run_config_command
    # Evict app/UI so we can detect a fresh import by the verb.
    for name in ("phonetic.app", "phonetic.tray", "phonetic.ui",
                 "phonetic.ui.settings"):
        sys.modules.pop(name, None)
    _run_config_command(_parse(["config", "add-profile", "X", "--hotkey",
                                "<ctrl>+<alt>+x"]))
    _run_config_command(_parse(["config", "list"]))
    _run_config_command(_parse(["config", "path"]))
    for name in ("phonetic.app", "phonetic.tray", "phonetic.ui",
                 "phonetic.ui.settings"):
        assert name not in sys.modules, f"config dispatch imported {name}"
