import os
import sys
import tkinter as tk
from typing import Optional, Callable

import customtkinter as ctk

from ..config import Config, save_config
from ..constants import DEFAULT_SYSTEM_PROMPT


class SettingsWindow(ctk.CTkToplevel):
    """Settings window. Doubles as first-run wizard when first_run=True."""

    def __init__(
        self,
        master: tk.Tk,
        config: Optional[Config],
        first_run: bool = False,
        on_save: Optional[Callable[[Config], None]] = None,
    ) -> None:
        super().__init__(master)
        self._config = config
        self._first_run = first_run
        self._on_save = on_save
        self._cancelled = False

        self.title("Phonetic — First Run Setup" if first_run else "Phonetic — Settings")
        self.geometry("500x580")
        self.resizable(False, True)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # Set window icon
        self._set_window_icon()

        # Bring to front
        self.lift()
        self.focus_force()

        self._build_ui()

    def _set_window_icon(self) -> None:
        """Set the window icon from assets."""
        try:
            from ..tray import _assets_dir
            icon_path = os.path.join(_assets_dir(), "icon.png")
            if os.path.exists(icon_path):
                self._icon_photo = tk.PhotoImage(file=icon_path)
                self.iconphoto(False, self._icon_photo)
        except Exception:
            pass

    def _build_ui(self) -> None:
        pad = {"padx": 16, "pady": (4, 4)}

        if self._first_run:
            header = ctk.CTkLabel(
                self, text="Welcome to Phonetic",
                font=ctk.CTkFont(size=18, weight="bold"),
            )
            header.pack(pady=(16, 4))
            sub = ctk.CTkLabel(
                self,
                text="Enter your OpenRouter API key to get started.",
                font=ctk.CTkFont(size=13),
            )
            sub.pack(pady=(0, 12))

        # API Key
        ctk.CTkLabel(self, text="OpenRouter API Key", anchor="w").pack(fill="x", **pad)
        self._api_key_var = ctk.StringVar(value=self._config.openrouter_api_key if self._config else "")
        key_frame = ctk.CTkFrame(self, fg_color="transparent")
        key_frame.pack(fill="x", padx=16, pady=(0, 4))
        self._api_key_entry = ctk.CTkEntry(key_frame, textvariable=self._api_key_var, show="*", width=380)
        self._api_key_entry.pack(side="left", fill="x", expand=True)
        self._show_key = False
        self._toggle_btn = ctk.CTkButton(key_frame, text="Show", width=60, command=self._toggle_key_visibility)
        self._toggle_btn.pack(side="right", padx=(8, 0))

        # Model
        ctk.CTkLabel(self, text="Model", anchor="w").pack(fill="x", **pad)
        self._model_var = ctk.StringVar(
            value=self._config.model if self._config else "google/gemini-3-flash-preview"
        )
        ctk.CTkEntry(self, textvariable=self._model_var).pack(fill="x", padx=16, pady=(0, 4))

        # Hotkey
        default_hotkey = "<cmd>+<shift>+r" if sys.platform == "darwin" else "<ctrl>+<alt>+r"
        ctk.CTkLabel(self, text="Hotkey", anchor="w").pack(fill="x", **pad)
        self._hotkey_var = ctk.StringVar(
            value=self._config.hotkey if self._config else default_hotkey
        )
        hotkey_frame = ctk.CTkFrame(self, fg_color="transparent")
        hotkey_frame.pack(fill="x", padx=16, pady=(0, 4))
        ctk.CTkEntry(hotkey_frame, textvariable=self._hotkey_var).pack(side="left", fill="x", expand=True)
        self._record_btn = ctk.CTkButton(hotkey_frame, text="Record", width=80, command=self._toggle_hotkey_record)
        self._record_btn.pack(side="right", padx=(8, 0))
        self._recording = False
        self._held_modifiers: set[str] = set()

        # Wayland setup section: interactive SIGUSR1 command + AI prompt copy
        if sys.platform.startswith("linux"):
            from ..platform_utils import _is_wayland
            if _is_wayland():
                self._build_wayland_section(pad)

        # Notifications
        self._notify_var = ctk.BooleanVar(value=self._config.notify if self._config else True)
        ctk.CTkCheckBox(self, text="Enable notifications", variable=self._notify_var).pack(
            anchor="w", padx=16, pady=(8, 4)
        )

        # Auto-start
        self._autostart_var = ctk.BooleanVar(value=self._config.auto_start if self._config else self._first_run)
        ctk.CTkCheckBox(self, text="Start at login", variable=self._autostart_var).pack(
            anchor="w", padx=16, pady=(4, 8)
        )

        # Advanced section (hidden in first-run)
        if not self._first_run:
            self._advanced_frame = ctk.CTkFrame(self, fg_color="transparent")
            self._advanced_visible = False
            self._advanced_toggle = ctk.CTkButton(
                self, text="Advanced \u25b6", width=100,
                fg_color="transparent", text_color=("gray10", "gray90"),
                hover_color=("gray80", "gray30"),
                command=self._toggle_advanced,
            )
            self._advanced_toggle.pack(anchor="w", padx=16, pady=(4, 0))

            ctk.CTkLabel(self._advanced_frame, text="System Prompt", anchor="w").pack(
                fill="x", padx=0, pady=(4, 4)
            )
            self._prompt_text = ctk.CTkTextbox(self._advanced_frame, height=120)
            self._prompt_text.pack(fill="both", expand=True, padx=0, pady=(0, 4))
            self._prompt_text.insert("1.0", self._config.system_prompt if self._config else DEFAULT_SYSTEM_PROMPT)
        else:
            self._advanced_frame = None

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=(12, 16), side="bottom")
        save_text = "Get Started" if self._first_run else "Save"
        ctk.CTkButton(btn_frame, text=save_text, command=self._on_save_click).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            btn_frame, text="Cancel", fg_color="transparent",
            text_color=("gray10", "gray90"),
            hover_color=("gray80", "gray30"),
            command=self._on_cancel,
        ).pack(side="right")

    def _build_wayland_section(self, pad: dict) -> None:
        """Build the Wayland SIGUSR1 setup section."""
        from ..setup_prompt import _pid_file_path, generate_setup_prompt

        frame = ctk.CTkFrame(self)
        frame.pack(fill="x", padx=16, pady=(4, 4))

        ctk.CTkLabel(
            frame,
            text="On Wayland, Phonetic uses SIGUSR1 for hotkey toggling.\n"
                 "Bind this command in your DE's keyboard settings:",
            font=ctk.CTkFont(size=12),
            anchor="w",
            justify="left",
        ).pack(fill="x", padx=12, pady=(8, 4))

        pid_path = _pid_file_path()
        sigusr1_cmd = f"kill -USR1 $(cat {pid_path})"

        cmd_entry = ctk.CTkEntry(frame, font=ctk.CTkFont(family="monospace", size=12))
        cmd_entry.insert(0, sigusr1_cmd)
        cmd_entry.configure(state="disabled")
        cmd_entry.pack(fill="x", padx=12, pady=(0, 4))

        btn_row = ctk.CTkFrame(frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(0, 8))

        def copy_command():
            self.clipboard_clear()
            self.clipboard_append(sigusr1_cmd)

        def copy_ai_prompt():
            hotkey = self._hotkey_var.get().strip()
            prompt = generate_setup_prompt(hotkey)
            self.clipboard_clear()
            self.clipboard_append(prompt)

        ctk.CTkButton(btn_row, text="Copy Command", width=130, command=copy_command).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="Copy AI Prompt", width=130, command=copy_ai_prompt).pack(side="left")

    def _toggle_key_visibility(self) -> None:
        self._show_key = not self._show_key
        self._api_key_entry.configure(show="" if self._show_key else "*")
        self._toggle_btn.configure(text="Hide" if self._show_key else "Show")

    def _toggle_advanced(self) -> None:
        if self._advanced_visible:
            self._advanced_frame.pack_forget()
            self._advanced_toggle.configure(text="Advanced \u25b6")
        else:
            self._advanced_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))
            self._advanced_toggle.configure(text="Advanced \u25bc")
        self._advanced_visible = not self._advanced_visible

    # -- Hotkey recorder (tkinter key bindings, main-thread safe) ----------

    # Map tkinter keysym → pynput modifier token
    _KEYSYM_TO_MOD: dict[str, str] = {
        "Meta_L": "<cmd>", "Meta_R": "<cmd>",
        "Super_L": "<cmd>", "Super_R": "<cmd>",
        "Shift_L": "<shift>", "Shift_R": "<shift>",
        "Control_L": "<ctrl>", "Control_R": "<ctrl>",
        "Alt_L": "<alt>", "Alt_R": "<alt>",
    }

    # macOS hardware keycode → base key (modifiers change keysym, but not keycode)
    _MAC_KEYCODE_TO_CHAR: dict[int, str] = {
        0: "a", 1: "s", 2: "d", 3: "f", 4: "h", 5: "g", 6: "z", 7: "x",
        8: "c", 9: "v", 11: "b", 12: "q", 13: "w", 14: "e", 15: "r",
        16: "y", 17: "t", 18: "1", 19: "2", 20: "3", 21: "4", 22: "6",
        23: "5", 24: "=", 25: "9", 26: "7", 27: "-", 28: "8", 29: "0",
        30: "]", 31: "o", 32: "u", 33: "[", 34: "i", 35: "p", 37: "l",
        38: "j", 40: "k", 43: ",", 44: "/", 45: "n", 46: "m", 47: ".",
        49: "space", 50: "`",
    }

    def _toggle_hotkey_record(self) -> None:
        if self._recording:
            self._stop_hotkey_record()
        else:
            self._start_hotkey_record()

    def _start_hotkey_record(self) -> None:
        self._recording = True
        self._held_modifiers.clear()
        self._record_btn.configure(text="Press keys…")
        self.bind("<KeyPress>", self._on_record_key_press)
        self.bind("<KeyRelease>", self._on_record_key_release)
        self.focus_set()

    def _stop_hotkey_record(self, combo: Optional[str] = None) -> None:
        self._recording = False
        self._held_modifiers.clear()
        self.unbind("<KeyPress>")
        self.unbind("<KeyRelease>")
        self._record_btn.configure(text="Record")
        if combo:
            self._hotkey_var.set(combo)

    def _on_record_key_press(self, event: tk.Event) -> str:
        keysym = event.keysym

        from ..log import log
        log(f"KEY keysym={keysym!r} keycode={event.keycode} char={event.char!r} state={event.state:#x}")

        # Escape cancels
        if keysym == "Escape":
            self._stop_hotkey_record()
            return "break"

        # Track modifiers
        mod = self._KEYSYM_TO_MOD.get(keysym)
        if mod:
            self._held_modifiers.add(mod)
            return "break"

        # Non-modifier key → resolve base key and build combo
        # On macOS, held modifiers change keysym (e.g. Cmd+Alt+r → "registered")
        # so use the hardware keycode to get the unmodified key.
        if sys.platform == "darwin" and event.keycode in self._MAC_KEYCODE_TO_CHAR:
            char = self._MAC_KEYCODE_TO_CHAR[event.keycode]
        elif len(keysym) == 1:
            char = keysym.lower()
        else:
            char = keysym.lower()
        mod_order = ["<cmd>", "<ctrl>", "<alt>", "<shift>"]
        mods = [m for m in mod_order if m in self._held_modifiers]
        parts = mods + [char]
        self._stop_hotkey_record("+".join(parts))
        return "break"

    def _on_record_key_release(self, event: tk.Event) -> str:
        mod = self._KEYSYM_TO_MOD.get(event.keysym)
        if mod:
            self._held_modifiers.discard(mod)
        return "break"

    def _on_cancel(self) -> None:
        if self._recording:
            self._stop_hotkey_record()
        self._cancelled = True
        if self._first_run and (self._config is None or not self._config.openrouter_api_key):
            from tkinter import messagebox
            if messagebox.askyesno(
                "Phonetic",
                "No API key configured. Phonetic cannot function without one.\n\nQuit?",
                parent=self,
            ):
                self.master.quit()
                return
            else:
                return
        self.destroy()

    def _on_save_click(self) -> None:
        if self._recording:
            self._stop_hotkey_record()
        api_key = self._api_key_var.get().strip()
        if not api_key:
            self._api_key_entry.configure(border_color="red")
            return

        # Validate hotkey
        hotkey = self._hotkey_var.get().strip()
        if hotkey:
            from ..hotkeys import validate_hotkey
            error = validate_hotkey(hotkey)
            if error:
                from tkinter import messagebox
                messagebox.showerror("Invalid Hotkey", f"'{hotkey}' is not a valid hotkey.\n\n{error}", parent=self)
                return

        # Build config, preserving auto-detected audio fields
        system_prompt = DEFAULT_SYSTEM_PROMPT
        if self._advanced_frame is not None and hasattr(self, "_prompt_text"):
            system_prompt = self._prompt_text.get("1.0", "end").strip() or DEFAULT_SYSTEM_PROMPT

        new_cfg = Config(
            openrouter_api_key=api_key,
            model=self._model_var.get().strip() or "google/gemini-3-flash-preview",
            hotkey=self._hotkey_var.get().strip(),
            sample_rate=self._config.sample_rate if self._config else 48000,
            channels=self._config.channels if self._config else 1,
            device=self._config.device if self._config else None,
            notify=self._notify_var.get(),
            system_prompt=system_prompt,
            auto_start=self._autostart_var.get(),
        )

        save_config(new_cfg)

        if self._on_save:
            self._on_save(new_cfg)

        self.destroy()

    @property
    def was_cancelled(self) -> bool:
        return self._cancelled
