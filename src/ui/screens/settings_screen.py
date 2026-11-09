"""Settings: API key, model/usage, updates."""
import webbrowser

import customtkinter as ctk

from src.services import api_key as key_store
from src.services import settings, updater
from src.services.gemini_service import DEFAULT_MODEL, validate_api_key
from src.ui import background, icons, theme as t
from src.version import __version__

MODEL_LABEL = DEFAULT_MODEL.replace("gemini-", "Gemini ").replace("-flash", " Flash").replace("-pro", " Pro")


def masked(key):
    if not key:
        return "Not set"
    return f"{key[:4]}{'•' * 24}{key[-4:]}" if len(key) > 10 else "•" * len(key)


class SettingsScreen(ctk.CTkFrame):
    def __init__(self, master, on_back, on_update_found, eur_rate=0.92):
        super().__init__(master, fg_color=t.SNOW, corner_radius=0)
        self.on_update_found = on_update_found
        self.eur_rate = eur_rate

        bar = ctk.CTkFrame(self, fg_color=t.SNOW, corner_radius=0, height=62)
        bar.pack(fill="x")
        ctk.CTkButton(bar, text="", image=icons.line_icon("arrow_left"), width=34, height=34,
                      corner_radius=8, fg_color=t.SNOW, hover_color=t.SNOWFIELD, border_width=1,
                      border_color=t.FROST, command=on_back).pack(side="left", padx=(24, 14), pady=14)
        t.label(bar, "Settings", size=15, weight="bold").pack(side="left")
        t.divider(self).pack(fill="x")

        col = ctk.CTkFrame(self, fg_color="transparent", width=640)
        col.pack(pady=(44, 0))
        col.pack_propagate(False)
        col.configure(height=600)

        # --- API key ---
        head = ctk.CTkFrame(col, fg_color="transparent")
        head.pack(fill="x")
        t.label(head, "Gemini API key", size=16, weight="bold").pack(side="left")
        self.pill = ctk.CTkLabel(head, text="", corner_radius=999, font=t.font(12, "bold"), height=24)
        self.pill.pack(side="right")
        t.label(col, "Used to read your invoices. It's stored in this computer's password store and "
                     "never leaves it, except to talk to Google.",
                size=14, color=t.LICHEN, wraplength=640).pack(anchor="w", fill="x", pady=(12, 14))

        row = ctk.CTkFrame(col, fg_color="transparent")
        row.pack(fill="x")
        self.key_entry = t.entry(row, mono_font=True)
        self.key_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.btn_key = t.secondary_button(row, "Replace", command=self._replace, width=96, height=42)
        self.btn_key.pack(side="right")
        self.lbl_key_msg = t.label(col, "", size=13, color=t.RED, wraplength=640)
        self.lbl_key_msg.pack(anchor="w", pady=(8, 0))
        t.link_button(col, "Get a key at aistudio.google.com ↗",
                      command=lambda: webbrowser.open("https://aistudio.google.com/apikey")).pack(anchor="w")
        t.divider(col).pack(fill="x", pady=(24, 0))

        # --- Model & usage ---
        sec = self._section(col, "AI model", f"{MODEL_LABEL} · about €0.003 per invoice")
        u = settings.month_usage()
        t.label(sec, f"This month: €{u['cost_usd'] * self.eur_rate:.2f} · {u['invoices']} invoices",
                size=13, color=t.LICHEN).pack(side="right")
        t.divider(col).pack(fill="x")

        # --- Updates ---
        sec = self._section(col, "Updates", f"Version {__version__}")
        self.lbl_update = sec.sub
        self.btn_update = t.secondary_button(sec, "Check now", command=self._check_updates, width=110)
        self.btn_update.pack(side="right")
        t.divider(col).pack(fill="x")

        self._show_key_state()

    def _section(self, parent, title, subtitle):
        sec = ctk.CTkFrame(parent, fg_color="transparent")
        sec.pack(fill="x", pady=28)
        left = ctk.CTkFrame(sec, fg_color="transparent")
        left.pack(side="left")
        t.label(left, title, size=16, weight="bold").pack(anchor="w")
        sec.sub = t.label(left, subtitle, size=14, color=t.LICHEN)
        sec.sub.pack(anchor="w", pady=(4, 0))
        return sec

    # --- API key ---
    def _show_key_state(self, editing=False):
        key = key_store.get_api_key()
        self.key_entry.configure(state="normal")
        self.key_entry.delete(0, "end")
        if editing:
            self.key_entry.configure(show="•")
            self.key_entry.focus_set()
            self.btn_key.configure(text="Save")
        else:
            self.key_entry.configure(show="")
            self.key_entry.insert(0, masked(key))
            self.key_entry.configure(state="disabled")
            self.btn_key.configure(text="Replace" if key else "Add key")
        self._pill("Working" if key else "Missing", ok=bool(key))

    def _pill(self, text, ok):
        self.pill.configure(text=f"  ●  {text}  ", fg_color=t.SELECTED if ok else t.RED_BG,
                            text_color=t.EVERGREEN if ok else t.RED)

    def _replace(self):
        if self.btn_key.cget("text") != "Save":
            self._show_key_state(editing=True)
            return
        key = self.key_entry.get().strip()
        if not key:
            self._show_key_state()
            return
        self.btn_key.configure(state="disabled", text="Checking…")

        background.run(self, lambda: validate_api_key(key), lambda err: self._key_checked(key, err))

    def _key_checked(self, key, err):
        self.btn_key.configure(state="normal")
        if err:
            self.btn_key.configure(text="Save")
            self.lbl_key_msg.configure(text=f"That key didn't work: {err}", text_color=t.RED)
            return
        key_store.save_api_key(key)
        self.lbl_key_msg.configure(text="Saved.", text_color=t.EVERGREEN)
        self._show_key_state()

    # --- Updates ---
    def _check_updates(self):
        self.btn_update.configure(state="disabled", text="Checking…")

        background.run(self, updater.check_for_update, self._update_checked)

    def _update_checked(self, info):
        self.btn_update.configure(state="normal", text="Check now")
        if info:
            self.lbl_update.configure(text=f"Version {__version__} · version {info.version} is available")
            self.on_update_found(info, show_dialog=True)
        else:
            self.lbl_update.configure(text=f"Version {__version__} · you have the latest version")
