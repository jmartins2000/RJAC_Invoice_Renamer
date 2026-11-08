"""First launch: ask for the Gemini API key."""
import threading
import webbrowser

import customtkinter as ctk

from src.services import api_key as key_store
from src.services.gemini_service import validate_api_key
from src.ui import icons, theme as t

AISTUDIO_URL = "https://aistudio.google.com/apikey"


class WelcomeScreen(ctk.CTkFrame):
    def __init__(self, master, on_done):
        super().__init__(master, fg_color=t.SNOW, corner_radius=0)
        self.on_done = on_done

        col = ctk.CTkFrame(self, fg_color="transparent", width=520)
        col.place(relx=0.5, rely=0.47, anchor="center")

        ctk.CTkLabel(col, text="", image=icons.logo(52)).pack(anchor="w", pady=(0, 28))
        ctk.CTkLabel(col, text="Welcome", font=t.display(44), text_color=t.INK, anchor="w").pack(anchor="w")
        t.label(col, "One thing before we start: paste your Gemini API key. It's what lets the app read "
                     "your invoices, and it stays on this computer.",
                size=15, color=t.LICHEN, wraplength=520).pack(anchor="w", pady=(10, 28))

        t.label(col, "Gemini API key", size=12, color=t.LICHEN).pack(anchor="w", pady=(0, 8))
        self.entry = t.entry(col, placeholder="AIza…", mono_font=True, width=520, show="•")
        self.entry.pack(anchor="w")
        self.entry.bind("<Return>", lambda _: self._check())
        t.link_button(col, "Don't have one? Get a key at aistudio.google.com ↗",
                      command=lambda: webbrowser.open(AISTUDIO_URL)).pack(anchor="w", pady=(6, 0))

        self.lbl_error = t.label(col, "", size=13, color=t.RED, wraplength=520)
        self.lbl_error.pack(anchor="w", pady=(10, 0))

        self.btn = t.primary_button(col, "Check key and continue", command=self._check, width=220)
        self.btn.pack(anchor="w", pady=(14, 0))
        self.after(150, self.entry.focus_set)

    def _check(self):
        key = self.entry.get().strip()
        if not key:
            self.lbl_error.configure(text="Paste your key in the box above.")
            return
        self.btn.configure(state="disabled", text="Checking…")
        self.lbl_error.configure(text="")

        def work():
            err = validate_api_key(key)
            self.after(0, lambda: self._checked(key, err))
        threading.Thread(target=work, daemon=True).start()

    def _checked(self, key, err):
        if err:
            self.btn.configure(state="normal", text="Check key and continue")
            self.lbl_error.configure(text=f"That key didn't work: {err}")
            return
        try:
            key_store.save_api_key(key)
        except Exception as e:
            self.btn.configure(state="normal", text="Check key and continue")
            self.lbl_error.configure(text=f"Couldn't save the key on this computer: {e}")
            return
        self.on_done()
