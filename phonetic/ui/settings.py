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

        # Bring to front
        self.lift()
        self.focus_force()

        self._build_ui()

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
        ctk.CTkEntry(self, textvariable=self._hotkey_var).pack(fill="x", padx=16, pady=(0, 4))

        # Notifications
        self._notify_var = ctk.BooleanVar(value=self._config.notify if self._config else True)
        ctk.CTkCheckBox(self, text="Enable notifications", variable=self._notify_var).pack(
            anchor="w", padx=16, pady=(8, 4)
        )

        # Auto-start
        self._autostart_var = ctk.BooleanVar(value=self._config.auto_start if self._config else False)
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

    def _on_save_click(self) -> None:
        api_key = self._api_key_var.get().strip()
        if not api_key:
            # Show inline error
            self._api_key_entry.configure(border_color="red")
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

    def _on_cancel(self) -> None:
        self._cancelled = True
        if self._first_run and (self._config is None or not self._config.openrouter_api_key):
            # Warn that app can't function
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

    @property
    def was_cancelled(self) -> bool:
        return self._cancelled
