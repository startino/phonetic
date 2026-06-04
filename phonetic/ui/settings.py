import os
import sys
import tkinter as tk
from typing import Optional, Callable

import customtkinter as ctk

import uuid

from ..config import Config, Profile
from .. import config_ops
from ..constants import DEFAULT_MODEL, DEFAULT_SYSTEM_PROMPT


class SettingsWindow(ctk.CTkToplevel):
    """Settings window. Doubles as first-run wizard when first_run=True."""

    def __init__(
        self,
        master: tk.Tk,
        config: Optional[Config],
        first_run: bool = False,
        on_save: Optional[Callable[[Config], None]] = None,
        on_hotkey_change: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(master)
        self._config = config
        self._first_run = first_run
        self._on_save = on_save
        self._on_hotkey_change = on_hotkey_change
        self._cancelled = False

        # Working copy of profiles for the (non-first-run) profile editor.
        self._profiles: list[Profile] = (
            [Profile(**vars(p)) for p in config.profiles]
            if (config and config.profiles) else []
        )
        self._selected_index: int = 0

        self.title("Phonetic — First Run Setup" if first_run else "Phonetic — Settings")
        self.geometry("520x680" if not first_run else "500x580")
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

        default_hotkey = "<cmd>+<shift>+r" if sys.platform == "darwin" else "<ctrl>+<alt>+r"
        self._recording = False
        self._held_modifiers: set[str] = set()

        if self._first_run:
            # Simple first-run: one model + one hotkey. The default profile is
            # synthesized from these on save.
            ctk.CTkLabel(self, text="Model", anchor="w").pack(fill="x", **pad)
            self._model_var = ctk.StringVar(
                value=self._config.model if self._config else DEFAULT_MODEL
            )
            ctk.CTkEntry(self, textvariable=self._model_var).pack(fill="x", padx=16, pady=(0, 4))

            ctk.CTkLabel(self, text="Hotkey", anchor="w").pack(fill="x", **pad)
            self._hotkey_var = ctk.StringVar(
                value=self._config.hotkey if self._config else default_hotkey
            )
            hotkey_frame = ctk.CTkFrame(self, fg_color="transparent")
            hotkey_frame.pack(fill="x", padx=16, pady=(0, 4))
            self._hotkey_entry = ctk.CTkEntry(hotkey_frame, textvariable=self._hotkey_var)
            self._hotkey_entry.pack(side="left", fill="x", expand=True)
            self._record_btn = ctk.CTkButton(hotkey_frame, text="Record", width=80, command=self._toggle_hotkey_record)
            self._record_btn.pack(side="right", padx=(8, 0))
            self._hotkey_status = ctk.CTkLabel(
                self,
                text="Press your hotkey anywhere to verify it works",
                font=ctk.CTkFont(size=12),
                text_color=("gray40", "gray60"),
                anchor="w",
            )
            self._hotkey_status.pack(fill="x", padx=16, pady=(0, 0))
        else:
            # Settings mode: per-keybind profile management.
            self._build_profiles_section(pad, default_hotkey)

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
        """Build the Wayland per-profile trigger setup section.

        On Wayland global hotkeys can't be grabbed, so each profile is triggered
        by a DE keyboard shortcut bound to `phonetic --trigger <profile-id>`.
        Every profile gets its OWN command — no default, full per-profile parity
        with X11/macOS.
        """
        frame = ctk.CTkFrame(self)
        frame.pack(fill="x", padx=16, pady=(4, 4))

        ctk.CTkLabel(
            frame,
            text="On Wayland, bind a DE keyboard shortcut to each profile's\n"
                 "command below (one per profile — no default profile):",
            font=ctk.CTkFont(size=12),
            anchor="w",
            justify="left",
        ).pack(fill="x", padx=12, pady=(8, 4))

        # One read-only command row + Copy button per profile.
        profiles = self._profiles if not self._first_run else []
        if not profiles:
            ctk.CTkLabel(
                frame,
                text="Add a profile first, then reopen Settings to see its "
                     "trigger command.",
                font=ctk.CTkFont(size=11),
                text_color=("gray40", "gray60"), anchor="w", justify="left",
            ).pack(fill="x", padx=12, pady=(0, 8))
            return

        for p in profiles:
            # Trigger by name (the identity). Quote names containing spaces so
            # the command is copy-pasteable into a compositor/DE binding.
            ref = p.name if p.name and " " not in p.name else f'"{p.name}"'
            cmd = f"phonetic --trigger {ref}"
            row = ctk.CTkFrame(frame, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=(0, 4))
            ctk.CTkLabel(
                row, text=p.name or "(unnamed)", width=120, anchor="w",
                font=ctk.CTkFont(size=11),
            ).pack(side="left")
            entry = ctk.CTkEntry(row, font=ctk.CTkFont(family="monospace", size=11))
            entry.insert(0, cmd)
            entry.configure(state="disabled")
            entry.pack(side="left", fill="x", expand=True, padx=(4, 4))

            def _copy(c=cmd):
                self.clipboard_clear()
                self.clipboard_append(c)

            ctk.CTkButton(row, text="Copy", width=60, command=_copy).pack(side="right")

    def _toggle_key_visibility(self) -> None:
        self._show_key = not self._show_key
        self._api_key_entry.configure(show="" if self._show_key else "*")
        self._toggle_btn.configure(text="Hide" if self._show_key else "Show")

    # -- Profile management (settings mode only) ---------------------------

    def _current_hotkey_value(self) -> str:
        """Return the hotkey string currently relevant for the open window."""
        if self._first_run:
            return self._hotkey_var.get().strip()
        return self._hotkey_var.get().strip() if hasattr(self, "_hotkey_var") else ""

    def _build_profiles_section(self, pad: dict, default_hotkey: str) -> None:
        """Build the per-keybind profile manager: list + editor panel."""
        ctk.CTkLabel(
            self, text="Profiles",
            font=ctk.CTkFont(size=14, weight="bold"), anchor="w",
        ).pack(fill="x", **pad)

        # Scrollable list of profiles.
        self._profile_list = ctk.CTkScrollableFrame(self, height=90)
        self._profile_list.pack(fill="x", padx=16, pady=(0, 4))

        # Add / Delete buttons.
        list_btns = ctk.CTkFrame(self, fg_color="transparent")
        list_btns.pack(fill="x", padx=16, pady=(0, 4))
        ctk.CTkButton(list_btns, text="Add Profile", width=110, command=self._add_profile).pack(side="left")
        self._delete_btn = ctk.CTkButton(
            list_btns, text="Delete Profile", width=120, command=self._delete_profile,
        )
        self._delete_btn.pack(side="left", padx=(8, 0))

        # Editor panel for the selected profile.
        editor = ctk.CTkFrame(self)
        editor.pack(fill="x", padx=16, pady=(4, 4))

        ctk.CTkLabel(editor, text="Name", anchor="w").pack(fill="x", padx=12, pady=(8, 0))
        self._name_var = ctk.StringVar()
        ctk.CTkEntry(editor, textvariable=self._name_var).pack(fill="x", padx=12, pady=(0, 4))
        self._name_var.trace_add("write", lambda *_: self._on_field_edit("name", self._name_var.get()))

        ctk.CTkLabel(editor, text="Hotkey", anchor="w").pack(fill="x", padx=12, pady=(4, 0))
        self._hotkey_var = ctk.StringVar()
        hotkey_frame = ctk.CTkFrame(editor, fg_color="transparent")
        hotkey_frame.pack(fill="x", padx=12, pady=(0, 4))
        self._hotkey_entry = ctk.CTkEntry(hotkey_frame, textvariable=self._hotkey_var)
        self._hotkey_entry.pack(side="left", fill="x", expand=True)
        self._record_btn = ctk.CTkButton(hotkey_frame, text="Record", width=80, command=self._toggle_hotkey_record)
        self._record_btn.pack(side="right", padx=(8, 0))
        self._hotkey_var.trace_add("write", lambda *_: self._on_field_edit("hotkey", self._hotkey_var.get()))
        self._hotkey_status = ctk.CTkLabel(
            editor,
            text="Press your hotkey anywhere to verify it works",
            font=ctk.CTkFont(size=12), text_color=("gray40", "gray60"), anchor="w",
        )
        self._hotkey_status.pack(fill="x", padx=12, pady=(0, 4))

        ctk.CTkLabel(editor, text="Model", anchor="w").pack(fill="x", padx=12, pady=(4, 0))
        self._model_var = ctk.StringVar()
        self._model_entry = ctk.CTkEntry(
            editor, textvariable=self._model_var,
            placeholder_text=f"{DEFAULT_MODEL} (single-call / fallback)",
        )
        self._model_entry.pack(fill="x", padx=12, pady=(0, 4))
        self._model_var.trace_add("write", lambda *_: self._on_field_edit("model", self._model_var.get()))

        ctk.CTkLabel(editor, text="ASR Model", anchor="w").pack(fill="x", padx=12, pady=(4, 0))
        self._asr_var = ctk.StringVar()
        self._asr_entry = ctk.CTkEntry(
            editor, textvariable=self._asr_var,
            placeholder_text="nvidia/parakeet-tdt-0.6b-v3 or leave blank",
        )
        self._asr_entry.pack(fill="x", padx=12, pady=(0, 4))
        self._asr_var.trace_add("write", lambda *_: self._on_field_edit("asr_model", self._asr_var.get()))

        ctk.CTkLabel(editor, text="Format Model", anchor="w").pack(fill="x", padx=12, pady=(4, 0))
        self._format_var = ctk.StringVar()
        self._format_entry = ctk.CTkEntry(
            editor, textvariable=self._format_var,
            placeholder_text="openai/gpt-4o or similar",
        )
        self._format_entry.pack(fill="x", padx=12, pady=(0, 4))
        self._format_var.trace_add("write", lambda *_: self._on_field_edit("format_model", self._format_var.get()))

        ctk.CTkLabel(editor, text="System Prompt", anchor="w").pack(fill="x", padx=12, pady=(4, 0))
        self._prompt_text = ctk.CTkTextbox(editor, height=100)
        self._prompt_text.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self._prompt_text.bind("<KeyRelease>", lambda _e: self._on_prompt_edit())

        # Seed one starter profile to edit when the user has none yet. This is
        # an ordinary profile (a real id + hotkey), NOT a privileged default \u2014
        # there is no default-profile concept anymore.
        if not self._profiles:
            self._profiles = [Profile(
                id=str(uuid.uuid4()), name="My Profile", hotkey=default_hotkey,
                model=DEFAULT_MODEL, asr_model="", format_model="",
                system_prompt=DEFAULT_SYSTEM_PROMPT,
            )]

        self._selected_index = 0
        self._refresh_profile_list()
        self._load_profile_into_editor(0)

    def _refresh_profile_list(self) -> None:
        """Redraw the profile list rows and the Delete button state."""
        for child in self._profile_list.winfo_children():
            child.destroy()
        for idx, p in enumerate(self._profiles):
            selected = idx == self._selected_index
            summary = p.asr_model or "single-call"
            label = f"{p.name or '(unnamed)'}  \u00b7  {p.hotkey or '(no hotkey)'}  \u00b7  {summary}"
            row = ctk.CTkButton(
                self._profile_list, text=label, anchor="w",
                fg_color=("gray75", "gray25") if selected else "transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray70", "gray30"),
                command=lambda i=idx: self._select_profile(i),
            )
            row.pack(fill="x", pady=1)
        # Delete is always available — zero profiles is a legal (if non-recording)
        # state now that there is no default profile.
        self._delete_btn.configure(state="disabled" if not self._profiles else "normal")

    def _select_profile(self, index: int) -> None:
        if not (0 <= index < len(self._profiles)):
            return
        self._commit_editor_to_profile()
        self._selected_index = index
        self._load_profile_into_editor(index)
        self._refresh_profile_list()

    def _load_profile_into_editor(self, index: int) -> None:
        if not (0 <= index < len(self._profiles)):
            return
        p = self._profiles[index]
        self._editor_loading = True
        self._name_var.set(p.name)
        self._hotkey_var.set(p.hotkey)
        self._model_var.set(p.model)
        self._asr_var.set(p.asr_model)
        self._format_var.set(p.format_model)
        self._prompt_text.delete("1.0", "end")
        self._prompt_text.insert("1.0", p.system_prompt)
        self._editor_loading = False

    def _commit_editor_to_profile(self) -> None:
        """Flush the editor widgets into the selected profile object."""
        if not (0 <= self._selected_index < len(self._profiles)):
            return
        p = self._profiles[self._selected_index]
        p.name = self._name_var.get().strip()
        p.hotkey = self._hotkey_var.get().strip()
        p.model = self._model_var.get().strip()
        p.asr_model = self._asr_var.get().strip()
        p.format_model = self._format_var.get().strip()
        p.system_prompt = self._prompt_text.get("1.0", "end").strip()

    def _on_field_edit(self, field_name: str, value: str) -> None:
        if getattr(self, "_editor_loading", False):
            return
        if not (0 <= self._selected_index < len(self._profiles)):
            return
        setattr(self._profiles[self._selected_index], field_name, value.strip())
        if field_name in ("name", "hotkey", "asr_model"):
            self._refresh_profile_list()

    def _on_prompt_edit(self) -> None:
        if getattr(self, "_editor_loading", False):
            return
        if not (0 <= self._selected_index < len(self._profiles)):
            return
        self._profiles[self._selected_index].system_prompt = self._prompt_text.get("1.0", "end").strip()

    def _add_profile(self) -> None:
        self._commit_editor_to_profile()
        new = Profile(
            id=str(uuid.uuid4()), name=f"Profile {len(self._profiles) + 1}",
            hotkey="", model=DEFAULT_MODEL, asr_model="", format_model="",
            system_prompt=DEFAULT_SYSTEM_PROMPT,
        )
        self._profiles.append(new)
        self._selected_index = len(self._profiles) - 1
        self._refresh_profile_list()
        self._load_profile_into_editor(self._selected_index)

    def _delete_profile(self) -> None:
        if not self._profiles:
            return
        self._profiles.pop(self._selected_index)
        self._selected_index = max(0, self._selected_index - 1)
        self._refresh_profile_list()
        if self._profiles:
            self._load_profile_into_editor(self._selected_index)
        else:
            self._clear_editor()

    def _clear_editor(self) -> None:
        """Blank the editor fields when no profile is selected."""
        self._editor_loading = True
        self._name_var.set("")
        self._hotkey_var.set("")
        self._model_var.set("")
        self._asr_var.set("")
        self._format_var.set("")
        self._prompt_text.delete("1.0", "end")
        self._editor_loading = False

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
            if self._on_hotkey_change:
                from ..log import log
                log(f"settings: hotkey recorded {combo!r}, notifying app")
                self._on_hotkey_change(combo)

    def _on_record_key_press(self, event: tk.Event) -> str:
        keysym = event.keysym
        from ..log import log
        log(f"KEY keysym={keysym!r} keycode={event.keycode} vk={(event.keycode >> 24) & 0xFF} char={event.char!r} state={event.state:#x}")

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
        # On macOS, tkinter encodes the virtual keycode in the upper byte
        if sys.platform == "darwin" and ((event.keycode >> 24) & 0xFF) in self._MAC_KEYCODE_TO_CHAR:
            char = self._MAC_KEYCODE_TO_CHAR[(event.keycode >> 24) & 0xFF]
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

    # -- Hotkey live verification (routed from App via real pynput) ---------

    def notify_hotkey_fired(self) -> None:
        """Called by App when the real pynput global hotkey fires while
        this settings window is open. Flashes the hotkey entry green."""
        from ..log import log
        import threading
        log(f"settings: notify_hotkey_fired() called on thread={threading.current_thread().name} id={threading.get_ident()}")
        log(f"settings: window exists={self.winfo_exists()}")
        try:
            self._hotkey_entry.configure(border_color="#22c55e")
            self._hotkey_status.configure(text="Hotkey works!", text_color="#22c55e")
            self.after(1200, self._reset_hotkey_status)
            log("settings: flashed green successfully")
        except Exception as exc:
            log(f"settings: ERROR flashing green: {exc}")

    def _reset_hotkey_status(self) -> None:
        """Reset hotkey entry border and hint text after flash."""
        try:
            self._hotkey_entry.configure(border_color=ctk.ThemeManager.theme["CTkEntry"]["border_color"])
        except Exception:
            self._hotkey_entry.configure(border_color=("#979DA2", "#565B5E"))
        self._hotkey_status.configure(
            text="Press your hotkey anywhere to verify it works",
            text_color=("gray40", "gray60"),
        )

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

        from ..hotkeys import validate_hotkey
        from tkinter import messagebox

        if self._first_run:
            # First run: the user's one model + hotkey become their FIRST real
            # profile (an ordinary profile with its own id) — not a default.
            hotkey = self._hotkey_var.get().strip()
            if hotkey:
                error = validate_hotkey(hotkey)
                if error:
                    messagebox.showerror("Invalid Hotkey", f"'{hotkey}' is not a valid hotkey.\n\n{error}", parent=self)
                    return
            model = self._model_var.get().strip() or DEFAULT_MODEL
            profiles = [Profile(
                id=str(uuid.uuid4()), name="My Profile", hotkey=hotkey,
                model=model, asr_model="", format_model="",
                system_prompt=DEFAULT_SYSTEM_PROMPT,
            )]
        else:
            # Settings mode: validate and collect all profiles.
            self._commit_editor_to_profile()
            profiles = self._profiles
            for p in profiles:
                if p.hotkey:
                    error = validate_hotkey(p.hotkey)
                    if error:
                        messagebox.showerror(
                            "Invalid Hotkey",
                            f"Profile '{p.name}' has an invalid hotkey '{p.hotkey}'.\n\n{error}",
                            parent=self,
                        )
                        return

        # Persist through the single writer (config_ops). The window assembles no
        # Config and calls no save_config — all config logic (the secret/toggle/
        # profile writes, the path asymmetry, the name-is-identity healing) lives
        # in config_ops. The returned Config is the in-memory DTO for the app
        # callback (audio fields carried through from the window's config).
        new_cfg = config_ops.save_from_ui(
            api_key=api_key,
            notify=self._notify_var.get(),
            auto_start=self._autostart_var.get(),
            profiles=profiles,
            sample_rate=self._config.sample_rate if self._config else 48000,
            channels=self._config.channels if self._config else 1,
            device=self._config.device if self._config else None,
            verbose=self._config.verbose if self._config else False,
        )

        if self._on_save:
            self._on_save(new_cfg)

        self.destroy()

    @property
    def was_cancelled(self) -> bool:
        return self._cancelled
