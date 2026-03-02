import os
import queue
import sys
import threading
import tkinter as tk
from typing import Optional

import numpy as np

from .clipboard import copy_to_clipboard
from .config import Config, load_config
from .log import log as _log
from .constants import MIN_DURATION_SECS, WARN_DURATION_SECS
from .hotkeys import HotkeyManager
from .notifications import notify
from .recorder import Recorder
from .transcribe import transcribe
from .tray import TrayManager


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
        self._root: Optional[object] = None  # tk.Tk when in GUI mode
        self._settings_win = None  # SettingsWindow ref for hotkey test routing

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

        _log(f"_run_gui: config loaded, cfg is None = {self._cfg is None}")
        if self._cfg is None:
            # First run — permissions first, then wizard
            if sys.platform == "darwin":
                _log("_run_gui: requesting accessibility")
                self._request_accessibility_interactive()
                _log("_run_gui: requesting mic permission")
                self._check_mic_permission()
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
        _log("_run_gui: entering mainloop")
        self._root.after(100, self._poll_messages)
        self._root.mainloop()

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
        default_hotkey = "<cmd>+<shift>+r" if sys.platform == "darwin" else "<ctrl>+<alt>+r"
        stub_cfg = Config(
            openrouter_api_key="",
            model="google/gemini-3-flash-preview",
            hotkey=default_hotkey,
            sample_rate=sample_rate,
            channels=channels,
            device=device,
            notify=True,
            system_prompt="",
            auto_start=True,
        )

        def on_first_run_save(cfg: Config) -> None:
            self._settings_win = None
            self._cfg = cfg
            if sys.platform == "darwin":
                self._hide_macos_dock()
            self._start_services()

        _log("first_run_wizard: opening SettingsWindow")
        self._settings_win = SettingsWindow(self._root, stub_cfg, first_run=True, on_save=on_first_run_save)
        _log("first_run_wizard: SettingsWindow created")

    def _check_accessibility(self) -> None:
        """On macOS, check Accessibility permission and warn if not granted."""

        if sys.platform != "darwin":
            return
        try:
            from ApplicationServices import AXIsProcessTrustedWithOptions
            trusted = AXIsProcessTrustedWithOptions(None)
            _log(f"accessibility: trusted={trusted}")
            if not trusted:
                print("Warning: Accessibility permission not granted. Global hotkey will not work.", file=sys.stderr)
                print("Grant in: System Settings → Privacy & Security → Accessibility", file=sys.stderr)
                self._notify("Hotkey disabled — grant Accessibility in System Settings", "critical")
        except Exception as exc:
            _log(f"accessibility: EXCEPTION: {exc}")
            pass

    def _request_accessibility_interactive(self) -> None:
        """On macOS first run, open System Settings for Accessibility and show
        a blocking messagebox so the user can grant the permission before
        proceeding."""

        if sys.platform != "darwin":
            return
        try:
            from ApplicationServices import AXIsProcessTrustedWithOptions
            trusted = AXIsProcessTrustedWithOptions(None)
            _log(f"accessibility_interactive: already trusted={trusted}")
            if trusted:
                return
        except Exception as exc:
            _log(f"accessibility_interactive: check failed: {exc}")
            return

        # Become foreground so the messagebox is visible
        try:
            from AppKit import (
                NSApplication,
                NSApplicationActivationPolicyRegular,
            )
            app = NSApplication.sharedApplication()
            app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
            app.activateIgnoringOtherApps_(True)
        except Exception as exc:
            _log(f"accessibility_interactive: foreground failed: {exc}")

        # Request with prompt — this registers the app in the accessibility
        # list in System Settings so the user can find and toggle it on.
        # Without the prompt option the app may not appear in the list at all.
        _log("accessibility_interactive: requesting with prompt (adds app to list)")
        try:
            AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": True})
        except Exception as exc:
            _log(f"accessibility_interactive: prompt request failed: {exc}")
            import subprocess
            subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"])

        # Block until user clicks OK
        from tkinter import messagebox
        messagebox.showinfo(
            "Phonetic — Accessibility Permission",
            "Phonetic needs Accessibility permission for global hotkeys.\n\n"
            "1. In the System Settings window that just opened, "
            "find Phonetic and toggle it ON\n"
            "2. Click OK here when done",
        )
        _log("accessibility_interactive: user dismissed dialog")

    def _start_services(self) -> None:
        """Start recorder, tray, and hotkeys after config is available."""

        assert self._cfg is not None

        # Check accessibility before starting hotkeys (macOS only)
        _log("start_services: checking accessibility")
        self._check_accessibility()
        _log(f"start_services: creating recorder (sr={self._cfg.sample_rate}, ch={self._cfg.channels}, dev={self._cfg.device})")

        self._rec = Recorder(
            sample_rate=self._cfg.sample_rate,
            channels=self._cfg.channels,
            device=self._cfg.device,
        )

        # Start tray
        self._tray = TrayManager(self._msg_queue)
        self._tray.set_device(self._cfg.device, self._cfg.device)
        self._tray.run()

        # Start hotkeys
        self._hotkeys = HotkeyManager(
            self._cfg.hotkey,
            on_toggle=lambda: self._msg_queue.put(("toggle_recording",)),
        )
        self._hotkeys.start()

        # Check for updates in the background
        threading.Thread(target=self._check_for_update, daemon=True).start()

        print(f"Ready. Press {self._cfg.hotkey} to start/stop recording.")

    def _check_for_update(self) -> None:
        from . import __version__
        from .update_check import check_for_update

        result = check_for_update(__version__)
        if result is not None:
            version, url = result
            self._msg_queue.put(("update_available", version, url))

    def _poll_messages(self) -> None:
        """Process all pending messages from the queue."""
        try:
            while True:
                msg = self._msg_queue.get_nowait()
                if isinstance(msg, str):
                    msg = (msg,)
                self._handle_message(msg)
        except queue.Empty:
            pass

        if self._root is not None:
            self._root.after(100, self._poll_messages)

    def _handle_message(self, msg: tuple[str, ...]) -> None:
        cmd = msg[0]

        if cmd == "toggle_recording":
            # Route to settings test UI if it's active
            if (self._settings_win is not None
                    and self._settings_win.winfo_exists()
                    and self._settings_win.is_testing):
                _log("handle_message: routing hotkey to settings test UI")
                self._settings_win.notify_hotkey_fired()
            else:
                self._toggle_recording()
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

    # --- Recording logic (same as original main.py:301-351) ---

    def _toggle_recording(self) -> None:

        if self._cfg is None or self._rec is None:
            return
        with self._processing_lock:
            if self._processing:
                return

        if not self._rec.is_recording:
            # Check mic permission before every recording attempt
            _log("toggle_recording: checking mic permission")
            mic_ok = self._check_mic_permission()
            _log(f"toggle_recording: mic_ok={mic_ok}")
            if not mic_ok:
                self._show_mic_denied_dialog()
                return
            _log("toggle_recording: starting recording")
            print(f"Recording... Press {self._cfg.hotkey} to stop.")
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
                self._tray.set_state(True)
        else:
            print("Stopping, processing...")
            audio = self._rec.stop()
            _log(f"toggle_recording: stopped, audio shape={audio.shape}, size={audio.size}")
            if self._tray:
                self._tray.set_state(False)
            self._notify("Transcribing...", "low", persist=True, replace=True)

            if audio.size == 0:
                _log("toggle_recording: no audio captured (size=0)")
                print("No audio captured.")
                self._notify("No audio captured", "critical", replace=True)
                return

            # Warn if audio is silent (common with wrong device or missing permissions)
            peak = float(np.max(np.abs(audio)))
            _log(f"toggle_recording: peak={peak:.6f}, duration={audio.shape[0]/self._rec.sample_rate:.2f}s")
            if peak < 0.001:
                if sys.platform == "darwin":
                    print("Warning: Audio appears silent. Check microphone permissions in "
                          "System Settings > Privacy & Security > Microphone.", file=sys.stderr)
                else:
                    print("Warning: Audio appears silent. Check that your microphone is "
                          "not muted and is set as the default input device.", file=sys.stderr)

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
                args=(audio, sample_rate),
                daemon=True,
            )
            thread.start()

    def _transcribe_worker(self, audio: np.ndarray, sample_rate: int) -> None:
        """Run transcription in a background thread and post result back."""
        try:
            text = transcribe(self._cfg, audio, sample_rate).strip()
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
            old_hotkey = self._cfg.hotkey if self._cfg else None
            self._cfg = cfg

            # Update autostart
            from .autostart import set_autostart
            set_autostart(cfg.auto_start)

            # Update hotkey if changed (requires restart on macOS)
            if self._hotkeys and old_hotkey != cfg.hotkey:
                try:
                    self._hotkeys.update_hotkey(cfg.hotkey)
                    if sys.platform == "darwin":
                        self._notify("Restart Phonetic for the new hotkey to take effect")
                except ValueError as e:
                    print(f"Hotkey error: {e}", file=sys.stderr)

        self._settings_win = SettingsWindow(self._root, self._cfg, on_save=on_settings_save)

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

        self._cfg = cfg
        self._rec = Recorder(
            sample_rate=cfg.sample_rate,
            channels=cfg.channels,
            device=cfg.device,
        )

        # Start hotkeys (includes SIGUSR1 on Linux)
        self._hotkeys = HotkeyManager(
            cfg.hotkey,
            on_toggle=lambda: self._msg_queue.put(("toggle_recording",)),
        )
        self._hotkeys.start()

        # Check for updates in the background
        threading.Thread(target=self._check_for_update, daemon=True).start()

        if self._hotkeys.signal_only:
            print("Ready. Waiting for SIGUSR1 to start/stop recording.")
        else:
            print(f"Ready. Press {cfg.hotkey} to start/stop recording.")
            if sys.platform.startswith("linux"):
                from .platform_utils import _is_wayland
                session_type = "wayland" if _is_wayland() else "x11"
                print(f"Session: {session_type}")

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

