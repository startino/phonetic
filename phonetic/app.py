import dataclasses
import os
import queue
import sys
import threading
import tkinter as tk
from typing import Optional

import numpy as np

from .clipboard import copy_to_clipboard
from .config import Config, Profile, load_config
from .control import ControlChannel
from .log import log as _log
from .constants import MIN_DURATION_SECS, WARN_DURATION_SECS
from .hotkeys import HotkeyManager
from .notifications import notify
from .recorder import Recorder
from .transcribe import transcribe
# NOTE: do NOT import .tray at module top. pystray opens the X display at import
# time and raises (not just ImportError) when there is no display — which would
# crash --headless / systemd-service startup before main() even runs. The tray
# is GUI-only; it is imported lazily in _start_services().


class UnknownProfileError(Exception):
    """A trigger fired carrying a profile_id that matches no configured profile.

    This means a stale/dangling hotkey registration (or an external --trigger
    with a bad id) survived a profile being deleted or its id changing. We raise
    instead of recording with some other profile, so the failure is visible
    rather than producing a transcription under the wrong profile's models.
    """

    def __init__(self, profile_id: str) -> None:
        self.profile_id = profile_id
        super().__init__(f"no profile matches profile_id={profile_id!r}")


class App:
    """Main application orchestrator.

    In GUI mode: runs a hidden tkinter root with .after() polling a message queue.
    In headless mode: runs a simple event loop with console output only.
    """

    def __init__(self, headless: bool = False) -> None:
        self._headless = headless
        self._msg_queue: queue.Queue[tuple[str, ...]] = queue.Queue()
        self._cfg: Optional[Config] = None
        self._rec: Optional[Recorder] = None
        self._processing = False
        self._processing_lock = threading.Lock()
        self._tray: Optional[TrayManager] = None
        self._hotkeys: Optional[HotkeyManager] = None
        self._control: Optional[ControlChannel] = None  # FIFO trigger channel
        self._root: Optional[object] = None  # tk.Tk when in GUI mode
        self._settings_win = None  # SettingsWindow ref for hotkey routing
        self._poll_count = 0  # message poll counter for heartbeat logging
        self._msg_count = 0  # total messages processed
        self._recording_profile_id = ""  # profile id of the in-flight recording

    def run(self) -> None:
        """Main entry point."""
        if self._headless:
            self._run_headless()
        else:
            self._run_gui()

    def _set_root_icon(self) -> None:
        """Set the root window icon so child windows inherit it."""
        try:
            from .tray import _assets_dir
            icon_path = os.path.join(_assets_dir(), "icon.png")
            if os.path.exists(icon_path):
                self._icon_photo = tk.PhotoImage(file=icon_path)
                self._root.iconphoto(True, self._icon_photo)
        except Exception:
            pass

    # --- GUI mode ---

    def _run_gui(self) -> None:

        _log("_run_gui: importing customtkinter")
        import customtkinter as ctk

        _log("_run_gui: setting appearance")
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        _log("_run_gui: creating CTk root")
        self._root = ctk.CTk()
        self._root.withdraw()  # Hidden — tray-only presence

        # Set window icon so all child windows inherit it
        self._set_root_icon()

        # Load config (or trigger first-run)
        _log("_run_gui: loading config")
        try:
            self._cfg = load_config(require_key=True)
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            from tkinter import messagebox
            messagebox.showerror("Phonetic", str(e))
            self._root.quit()
            return

        if self._cfg is not None:
            from .log import set_verbose
            set_verbose(self._cfg.verbose)
        _log(f"_run_gui: config loaded, cfg is None = {self._cfg is None}")
        if self._cfg is None:
            # First run — mic permission, then wizard
            if sys.platform == "darwin":
                _log("_run_gui: requesting mic permission")
                self._check_mic_permission()
                _log("_run_gui: hiding from dock")
                self._hide_macos_dock()
            _log("_run_gui: showing first-run wizard")
            self._show_first_run_wizard()
        else:
            # Returning user — request mic permission while still foreground, then hide
            if sys.platform == "darwin":
                _log("_run_gui: checking mic permission")
                self._check_mic_permission()
                _log("_run_gui: hiding from dock")
                self._hide_macos_dock()
            _log("_run_gui: starting services")
            self._start_services()

        # Start message queue polling
        _log(f"_run_gui: scheduling first poll, thread={threading.current_thread().name} id={threading.get_ident()}")
        self._root.after(100, self._poll_messages)
        _log("_run_gui: entering mainloop NOW")
        self._root.mainloop()
        _log("_run_gui: mainloop exited")

        # Cleanup
        self._shutdown()

    def _show_first_run_wizard(self) -> None:

        from .ui.settings import SettingsWindow
        from .audio_detect import detect_audio

        # Create a minimal config with detected audio for the settings window
        _log("first_run_wizard: detecting audio")
        try:
            sample_rate, channels, device = detect_audio()
            _log(f"first_run_wizard: audio detected sr={sample_rate} ch={channels} dev={device}")
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            from tkinter import messagebox
            messagebox.showerror("Phonetic", str(e))
            self._root.quit()
            return
        stub_cfg = Config(
            openrouter_api_key="",
            sample_rate=sample_rate,
            channels=channels,
            device=device,
            notify=True,
            auto_start=True,
        )

        # Start an early hotkey manager so the user can verify a hotkey works
        # while still in the wizard. Same timing as the non-first-run path
        # (before mainloop) which avoids the TSM crash on Sequoia. The wizard
        # registers the profile-in-progress via on_hotkey_change.
        _log("first_run_wizard: starting early hotkey manager")
        self._hotkeys = HotkeyManager("", on_toggle=lambda: None)
        self._hotkeys.start()
        _log(f"first_run_wizard: early hotkey manager started, type={type(self._hotkeys).__name__}")

        def on_first_run_save(cfg: Config) -> None:
            _log("on_first_run_save: wizard save triggered")
            self._settings_win = None
            self._cfg = cfg
            # Stop the early listener — _start_services creates a fresh one
            if self._hotkeys is not None:
                _log("on_first_run_save: stopping early hotkey listener")
                self._hotkeys.stop()
                self._hotkeys = None
            if sys.platform == "darwin":
                self._hide_macos_dock()
            _log("on_first_run_save: starting services")
            self._start_services()
            _log("on_first_run_save: services started")

        def on_hotkey_change(new_hotkey: str) -> None:
            _log(f"on_hotkey_change: {new_hotkey!r}")
            if self._hotkeys is not None:
                self._hotkeys.update_hotkey(new_hotkey)

        _log("first_run_wizard: opening SettingsWindow")
        self._settings_win = SettingsWindow(
            self._root, stub_cfg, first_run=True,
            on_save=on_first_run_save,
            on_hotkey_change=on_hotkey_change,
        )
        _log("first_run_wizard: SettingsWindow created")

    def _start_services(self) -> None:
        """Start recorder, tray, and hotkeys after config is available."""

        assert self._cfg is not None
        _log(f"start_services: creating recorder (sr={self._cfg.sample_rate}, ch={self._cfg.channels}, dev={self._cfg.device})")

        self._rec = Recorder(
            sample_rate=self._cfg.sample_rate,
            channels=self._cfg.channels,
            device=self._cfg.device,
        )

        # Start tray, populated with every profile as a directly-listed entry.
        # Imported lazily (GUI-only) — see the note at the top of this module.
        from .tray import TrayManager
        self._tray = TrayManager(self._msg_queue)
        self._tray.set_device(self._cfg.device, self._cfg.device)
        self._tray.set_profiles(self._cfg.profiles)
        self._tray.run()

        # Start the hotkey manager (no single global hotkey — profiles own them).
        # The base on_toggle is unused now; every recording carries a profile id.
        self._hotkeys = HotkeyManager("", on_toggle=lambda: None)
        self._hotkeys.start()
        _log(f"start_services: hotkey manager started, type={type(self._hotkeys).__name__}")

        # Register each profile's own hotkey.
        self._register_profile_hotkeys()

        # Start the control channel so `phonetic --trigger <id>` works (Wayland
        # per-profile triggers + any external automation).
        self._start_control_channel()

        # Check for updates in the background
        threading.Thread(target=self._check_for_update, daemon=True).start()

        n = len(self._cfg.profiles)
        if n:
            print(f"Ready. {n} profile(s) loaded — press a profile's hotkey, "
                  f"or pick one from the tray, to record.")
        else:
            print("Ready, but no profiles are configured. Open Settings to add "
                  "one — there is no default profile.")
            self._notify("No profiles configured — open Settings to add one",
                         "normal")

    def _start_control_channel(self) -> None:
        """Start the FIFO control channel that maps --trigger <id> to a profile."""
        def _on_trigger(profile_id: str) -> None:
            _log(f"control: dispatching trigger profile_id={profile_id!r}")
            self._msg_queue.put(("toggle_recording", profile_id))

        self._control = ControlChannel(_on_trigger)
        if self._control.start():
            _log("start_services: control channel started")
        else:
            _log("start_services: control channel unavailable")

    def _register_profile_hotkeys(self) -> None:
        """Register every profile's hotkey on the active hotkey manager."""
        if self._hotkeys is None or self._cfg is None or not self._cfg.profiles:
            return

        def _on_toggle_for_profile(profile_id: str) -> None:
            _log(f"on_toggle_for_profile: FIRED profile_id={profile_id!r} "
                 f"thread={threading.current_thread().name} id={threading.get_ident()}")
            self._msg_queue.put(("toggle_recording", profile_id))

        try:
            _log(f"register_profile_hotkeys: registering {len(self._cfg.profiles)} profile(s)")
            self._hotkeys.update_hotkeys(self._cfg.profiles, _on_toggle_for_profile)
        except Exception as e:
            _log(f"register_profile_hotkeys: FAILED: {e}")

    def _check_for_update(self) -> None:
        from . import __version__
        from .update_check import check_for_update

        result = check_for_update(__version__)
        if result is not None:
            version, url = result
            self._msg_queue.put(("update_available", version, url))

    def _poll_messages(self) -> None:
        """Process all pending messages from the queue."""
        self._poll_count += 1
        # Log heartbeat every 300 polls (~30 seconds at 100ms interval)
        if self._poll_count % 300 == 0:
            qsize = self._msg_queue.qsize()
            _log(f"poll_heartbeat: poll#{self._poll_count} msgs_processed={self._msg_count} "
                 f"queue_size={qsize} hotkeys={self._hotkeys!r} "
                 f"settings_win={'open' if self._settings_win is not None else 'closed'} "
                 f"thread={threading.current_thread().name}")
        try:
            while True:
                msg = self._msg_queue.get_nowait()
                if isinstance(msg, str):
                    msg = (msg,)
                self._msg_count += 1
                self._handle_message(msg)
        except queue.Empty:
            pass

        if self._root is not None:
            self._root.after(100, self._poll_messages)

    def _handle_message(self, msg: tuple[str, ...]) -> None:
        cmd = msg[0]
        _log(f"handle_message: cmd={cmd!r} msg_total={self._msg_count} thread={threading.current_thread().name}")

        if cmd == "toggle_recording":
            profile_id = msg[1] if len(msg) > 1 else ""
            # Route to settings window for visual feedback if open
            sw = self._settings_win
            sw_exists = sw is not None and sw.winfo_exists() if sw is not None else False
            _log(f"handle_message: toggle_recording — profile_id={profile_id!r} settings_win={sw!r} exists={sw_exists} cfg_loaded={self._cfg is not None}")
            if sw_exists:
                _log("handle_message: routing hotkey to settings window for visual feedback")
                self._settings_win.notify_hotkey_fired()
                _log("handle_message: notify_hotkey_fired() returned")
            else:
                _log(f"handle_message: no settings window, calling _toggle_recording(profile_id={profile_id!r})")
                self._toggle_recording(profile_id)
        elif cmd == "show_settings":
            self._show_settings()
        elif cmd == "quit":
            if self._root is not None:
                self._root.quit()
        elif cmd == "transcription_done":
            text = msg[1] if len(msg) > 1 else ""
            self._on_transcription_done(text)
        elif cmd == "transcription_error":
            error = msg[1] if len(msg) > 1 else "Unknown error"
            self._on_transcription_error(error)
        elif cmd == "update_available":
            version = msg[1] if len(msg) > 1 else ""
            url = msg[2] if len(msg) > 2 else ""
            print(f"Update available: v{version} — {url}")
            self._notify(f"Update available: v{version}")
        elif cmd == "device_changed":
            idx = msg[1] if len(msg) > 1 else None
            self._on_device_changed(idx)
        elif cmd == "config_reloaded":
            cfg = msg[1] if len(msg) > 1 else None
            if cfg is not None:
                self._cfg = cfg

    # --- Profile resolution ---

    def _resolve_profile(self, profile_id: str) -> Profile:
        """Return the Profile for profile_id. Always requires an explicit id.

        There is no default profile and no blank→first fallback: every trigger
        (a profile's own hotkey, a tray selection, or an external --trigger)
        names exactly one profile. A blank or unknown id raises
        ``UnknownProfileError`` so the failure is surfaced rather than papered
        over by recording with the wrong profile.
        """
        if self._cfg is None or not self._cfg.profiles or not profile_id:
            raise UnknownProfileError(profile_id)
        for p in self._cfg.profiles:
            if p.id == profile_id:
                return p
        raise UnknownProfileError(profile_id)

    # --- Recording logic (same as original main.py:301-351) ---

    def _toggle_recording(self, profile_id: str = "") -> None:

        if self._cfg is None or self._rec is None:
            return
        with self._processing_lock:
            if self._processing:
                return

        # If a DIFFERENT profile's hotkey fires while recording, stop the
        # current recording and immediately start a fresh one for the new
        # profile. Same-profile hotkey while recording = stop (handled below).
        if (
            self._rec.is_recording
            and profile_id
            and self._recording_profile_id
            and profile_id != self._recording_profile_id
        ):
            _log(f"toggle_recording: profile switch while recording — "
                 f"stopping profile={self._recording_profile_id!r}, "
                 f"starting profile={profile_id!r}")
            self._stop_recording_and_transcribe(self._recording_profile_id)
            _log(f"toggle_recording: starting new recording for profile={profile_id!r}")
            self._start_recording(profile_id)
            return

        if not self._rec.is_recording:
            self._start_recording(profile_id)
        else:
            self._stop_recording_and_transcribe(self._recording_profile_id)

    def _start_recording(self, profile_id: str = "") -> None:
        """Begin a recording, remembering which profile it belongs to."""
        # Check mic permission before every recording attempt
        _log("toggle_recording: checking mic permission")
        mic_ok = self._check_mic_permission()
        _log(f"toggle_recording: mic_ok={mic_ok}")
        if not mic_ok:
            self._show_mic_denied_dialog()
            return
        try:
            profile = self._resolve_profile(profile_id)
        except UnknownProfileError as e:
            _log(f"toggle_recording: REFUSING to record — {e}")
            print(f"Trigger fired for unknown profile {e.profile_id!r}; not "
                  f"recording. A stale hotkey is registered for a deleted "
                  f"profile — fix your profiles.", file=sys.stderr)
            self._notify("Trigger points at a profile that no longer exists — "
                         "not recording", "critical")
            return
        self._recording_profile_id = profile.id
        _log(f"toggle_recording: starting recording for profile_id={self._recording_profile_id!r} "
             f"name={profile.name!r}")
        print(f"Recording with profile {profile.name!r}... press its hotkey to stop.")
        try:
            self._rec.start()
            _log(f"toggle_recording: recording started, device={self._rec.device} sr={self._rec.sample_rate}")
        except Exception as e:
            _log(f"toggle_recording: start FAILED: {e}")
            print(f"Audio input error: {e}", file=sys.stderr)
            self._notify(f"Audio input error: {e}", "critical")
            return
        self._notify("Recording started", "low", persist=True)
        if self._tray:
            self._tray.set_state(True, self._recording_profile_id)
        # Schedule early audio check after 1 second to catch silent input
        if self._root is not None:
            self._root.after(1000, self._check_early_audio)
        else:
            threading.Timer(1.0, self._check_early_audio).start()

    def _stop_recording_and_transcribe(self, profile_id: str = "") -> None:
        """Stop the current recording and hand audio to the transcribe worker."""
        print("Stopping, processing...")
        audio = self._rec.stop()
        _log(f"toggle_recording: stopped, audio shape={audio.shape}, size={audio.size} "
             f"profile_id={profile_id!r}")
        self._recording_profile_id = ""
        if self._tray:
            self._tray.set_state(False)
        self._notify("Transcribing...", "low", persist=True, replace=True)

        if audio.size == 0:
            _log("toggle_recording: no audio captured (size=0)")
            print("No audio captured.")
            self._notify("No audio captured", "critical", replace=True)
            return

        # Warn if audio appears silent but still attempt transcription —
        # some backends (PipeWire/ALSA) deliver low-level data that
        # transcribes fine despite a low float32 peak
        peak = float(np.max(np.abs(audio)))
        _log(f"toggle_recording: peak={peak:.6f}, duration={audio.shape[0]/self._rec.sample_rate:.2f}s")
        if peak < 0.001:
            if sys.platform == "darwin":
                msg = "Audio may be silent — check microphone permissions"
            else:
                msg = "Audio may be silent — check that your mic is not muted"
            print(msg, file=sys.stderr)
            self._notify(msg, "normal")

        duration = audio.shape[0] / self._rec.sample_rate
        if duration < MIN_DURATION_SECS:
            print(f"Recording too short ({duration:.1f}s), skipping.")
            self._notify("Recording too short", "low", replace=True)
            return
        if duration > WARN_DURATION_SECS:
            print(f"Warning: long recording ({duration:.0f}s), upload may be slow.", file=sys.stderr)

        with self._processing_lock:
            self._processing = True
        # Run transcription in a worker thread
        sample_rate = self._rec.sample_rate
        thread = threading.Thread(
            target=self._transcribe_worker,
            args=(audio, sample_rate, profile_id),
            daemon=True,
        )
        thread.start()

    def _check_early_audio(self) -> None:
        """Check audio level after 1s of recording and warn if silent."""
        if self._rec is None or not self._rec.is_recording:
            return
        peak = self._rec.peek_level()
        _log(f"early_audio_check: peak={peak:.6f}")
        if peak < 0.001:
            _log("early_audio_check: low audio level — warning (recording continues)")
            if sys.platform == "darwin":
                msg = "Low/no audio — check microphone permissions in System Settings"
            else:
                msg = "Low/no audio — check that your mic is not muted"
            print(msg, file=sys.stderr)
            self._notify(msg, "normal", replace=True)

    def _transcribe_worker(self, audio: np.ndarray, sample_rate: int, profile_id: str) -> None:
        """Run transcription in a background thread and post result back.

        Builds the transcribe config entirely from the active profile — model,
        ASR/format models, and system prompt all come from the profile, with the
        built-in defaults filling any blanks. There is no global model anymore.
        """
        from .constants import DEFAULT_MODEL, DEFAULT_SYSTEM_PROMPT
        try:
            profile = self._resolve_profile(profile_id)
            model = profile.model or DEFAULT_MODEL
            _log(f"transcribe_worker: profile id={profile.id!r} name={profile.name!r} "
                 f"model={model!r} asr={profile.asr_model!r} format={profile.format_model!r}")
            cfg = dataclasses.replace(
                self._cfg,
                model=model,
                asr_model=profile.asr_model,
                format_model=profile.format_model or model,
                system_prompt=profile.system_prompt or DEFAULT_SYSTEM_PROMPT,
            )
            text = transcribe(cfg, audio, sample_rate).strip()
            self._msg_queue.put(("transcription_done", text))
        except Exception as e:
            self._msg_queue.put(("transcription_error", str(e)))

    def _on_transcription_done(self, text: str) -> None:
        with self._processing_lock:
            self._processing = False
        if text:
            try:
                copy_to_clipboard(text)
                print("Transcription copied to clipboard.")
                preview = text if len(text) <= 120 else text[:117] + "..."
                self._notify(f"\u201c{preview}\u201d", replace=True)
            except Exception as e:
                print(f"Clipboard unavailable: {e}", file=sys.stderr)
                print("Transcription (not copied):\n" + text)
                self._notify("Transcription ready (clipboard unavailable)", replace=True)
        else:
            print("Empty transcription.")
            self._notify("Empty transcription", "low", replace=True)

    def _on_transcription_error(self, error: str) -> None:
        with self._processing_lock:
            self._processing = False
        print(f"Error: {error}", file=sys.stderr)
        preview = error if len(error) <= 120 else error[:117] + "..."
        self._notify(preview, "critical", replace=True)

    def _on_device_changed(self, idx: Optional[int]) -> None:
        """Handle a device change from the tray submenu (session-only)."""
        if self._rec is None or self._cfg is None:
            return
        self._rec.device = idx
        self._cfg.device = idx
        # Re-detect sample rate for the new device
        try:
            if idx is None:
                from .audio_detect import detect_audio
                sample_rate, _channels, _dev = detect_audio()
            else:
                import sounddevice as sd
                sample_rate = int(sd.query_devices(idx)["default_samplerate"])
            self._rec.sample_rate = sample_rate
            self._cfg.sample_rate = sample_rate
        except Exception as e:
            print(f"Warning: could not detect sample rate for device {idx}: {e}")

    def _notify(self, body: str, urgency: str = "normal", persist: bool = False, replace: bool = False) -> None:
        enabled = self._cfg.notify if self._cfg else True
        notify(body, urgency=urgency, persist=persist, replace=replace,
               enabled=enabled, tray=self._tray)

    # --- Settings ---

    def _show_settings(self) -> None:
        if self._root is None or self._cfg is None:
            return

        from .ui.settings import SettingsWindow

        def on_settings_save(cfg: Config) -> None:
            self._settings_win = None
            self._cfg = cfg

            # Update autostart
            from .autostart import set_autostart
            set_autostart(cfg.auto_start)

            # Re-register every profile's hotkey, and refresh the tray's
            # directly-listed profile entries (covers add/remove/rename/rebind).
            if self._hotkeys is not None:
                self._register_profile_hotkeys()
            if self._tray is not None:
                self._tray.set_profiles(cfg.profiles)

        def on_settings_hotkey_change(new_hotkey: str) -> None:
            _log(f"on_settings_hotkey_change: {new_hotkey!r}")
            if self._hotkeys is not None:
                self._hotkeys.update_hotkey(new_hotkey)

        self._settings_win = SettingsWindow(
            self._root, self._cfg, on_save=on_settings_save,
            on_hotkey_change=on_settings_hotkey_change,
        )

    # --- macOS dock hiding ---

    def _check_mic_permission(self) -> bool:
        """Check microphone authorization on macOS.

        If undetermined, triggers the system permission dialog via AVFoundation
        (must be called while the app is a foreground app for the dialog to be
        visible). Returns True if authorized, False otherwise.
        """

        if sys.platform != "darwin":
            return True
        try:
            import objc
            _log("mic_perm: loading AVFoundation")
            objc.loadBundle(
                "AVFoundation", {},
                bundle_path="/System/Library/Frameworks/AVFoundation.framework",
            )

            # Register block signature so PyObjC knows how to call the completion handler
            objc.registerMetaDataForSelector(
                b"AVCaptureDevice",
                b"requestAccessForMediaType:completionHandler:",
                {
                    "arguments": {
                        3: {
                            "callable": {
                                "retval": {"type": b"v"},
                                "arguments": {
                                    0: {"type": b"^v"},
                                    1: {"type": b"Z"},
                                },
                            }
                        }
                    }
                },
            )

            AVCaptureDevice = objc.lookUpClass("AVCaptureDevice")
            status = AVCaptureDevice.authorizationStatusForMediaType_("soun")
            _log(f"mic_perm: status = {status} (0=notDetermined, 1=restricted, 2=denied, 3=authorized)")
            if status == 3:  # Authorized
                return True
            if status == 0:  # Not determined — trigger the system dialog
                _log("mic_perm: not determined, becoming foreground app")
                from AppKit import (
                    NSApplication,
                    NSApplicationActivationPolicyRegular,
                )
                app = NSApplication.sharedApplication()
                app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
                app.activateIgnoringOtherApps_(True)

                _log("mic_perm: requesting access via AVCaptureDevice")
                event = threading.Event()
                granted_box: list[bool] = [False]

                def _handler(granted: bool) -> None:
                    _log(f"mic_perm: handler called, granted={granted}")
                    granted_box[0] = granted
                    event.set()

                AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                    "soun", _handler,
                )
                _log("mic_perm: waiting for user response")
                event.wait(timeout=120)
                _log(f"mic_perm: result = {granted_box[0]}")
                return granted_box[0]
            # Denied (2) or Restricted (1)
            _log("mic_perm: denied/restricted, returning False")
            return False
        except Exception as exc:
            _log(f"mic_perm: EXCEPTION: {exc}")
            return False

    def _show_mic_denied_dialog(self) -> None:
        """Show a dialog telling the user to enable mic permission in System Settings."""

        _log("mic_denied_dialog: showing")
        try:
            from AppKit import (
                NSApplication,
                NSApplicationActivationPolicyRegular,
                NSApplicationActivationPolicyAccessory,
            )
            app = NSApplication.sharedApplication()
            app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
            from tkinter import messagebox
            messagebox.showwarning(
                "Phonetic — Microphone Required",
                "Phonetic needs microphone access to record audio.\n\n"
                "1. Open System Settings \u2192 Privacy & Security \u2192 Microphone\n"
                "2. Find Phonetic and toggle it ON\n"
                "3. Try recording again",
            )
            app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        except Exception:
            pass

    def _hide_macos_dock(self) -> None:
        try:
            from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
            NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        except ImportError:
            pass

    # --- Shutdown ---

    def _shutdown(self) -> None:
        if self._rec and self._rec.is_recording:
            self._rec.stop()
        if self._hotkeys:
            self._hotkeys.stop()
        if self._control:
            self._control.stop()
        if self._tray:
            self._tray.stop()

    # --- Headless mode ---

    def _run_headless(self) -> None:
        """Run in headless/console mode (original behavior for systemd/CLI)."""
        try:
            cfg = load_config(require_key=False)
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        if cfg is None or not cfg.openrouter_api_key:
            print("OPENROUTER_API_KEY is required", file=sys.stderr)
            sys.exit(1)

        from .log import set_verbose
        set_verbose(cfg.verbose)
        self._cfg = cfg
        self._rec = Recorder(
            sample_rate=cfg.sample_rate,
            channels=cfg.channels,
            device=cfg.device,
        )

        # Hotkey manager with no global hotkey — each profile owns its own.
        self._hotkeys = HotkeyManager("", on_toggle=lambda: None)
        self._hotkeys.start()
        _log(f"run_headless: hotkey manager started, type={type(self._hotkeys).__name__}")

        # Register each profile's own hotkey.
        self._register_profile_hotkeys()

        # Start the control channel so `phonetic --trigger <id>` records a
        # specific profile (the Wayland path, where hotkeys can't be grabbed).
        self._start_control_channel()

        # Check for updates in the background
        threading.Thread(target=self._check_for_update, daemon=True).start()

        n = len(cfg.profiles)
        if self._hotkeys.signal_only:
            print(f"Ready. {n} profile(s) loaded. Global hotkeys are unavailable "
                  f"here — trigger a profile with: phonetic --trigger <profile-id>")
        else:
            print(f"Ready. {n} profile(s) loaded — press a profile's hotkey to record.")
        if sys.platform.startswith("linux"):
            from .platform_utils import _is_wayland
            session_type = "wayland" if _is_wayland() else "x11"
            print(f"Session: {session_type}")
        if not n:
            print("No profiles configured. Edit profiles.json (see "
                  "profiles.json.example) and restart.", file=sys.stderr)

        print("Press Ctrl+C to exit.")
        try:
            while True:
                # In headless mode, process messages synchronously
                try:
                    msg = self._msg_queue.get(timeout=0.5)
                    if isinstance(msg, str):
                        msg = (msg,)
                    self._handle_message(msg)
                except queue.Empty:
                    pass
        except KeyboardInterrupt:
            pass
        finally:
            self._shutdown()

