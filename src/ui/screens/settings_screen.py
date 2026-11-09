"""Settings: API key, model/usage, updates."""
import webbrowser

import customtkinter as ctk

from src.services import api_key as key_store
from src.services import models, settings, updater
from src.services.gemini_service import validate_api_key
from src.ui import background, icons, theme as t
from src.version import __version__


def masked(key):
    if not key:
        return "Not set"
    return f"{key[:4]}{'•' * 24}{key[-4:]}" if len(key) > 10 else "•" * len(key)


class SettingsScreen(ctk.CTkFrame):
    def __init__(self, master, on_back, on_update_found, on_fields, eur_rate=0.92):
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
        msec = ctk.CTkFrame(col, fg_color="transparent")
        msec.pack(fill="x", pady=28)
        mhead = ctk.CTkFrame(msec, fg_color="transparent")
        mhead.pack(fill="x")
        t.label(mhead, "AI model", size=16, weight="bold").pack(side="left")
        u = settings.month_usage()
        t.label(mhead, f"This month: €{u['cost_usd'] * self.eur_rate:.2f} · {u['invoices']} invoices",
                size=13, color=t.LICHEN).pack(side="right")
        menu_box = ctk.CTkFrame(msec, fg_color=t.SNOW, corner_radius=8, border_width=1, border_color=t.FIELD_BORDER)
        menu_box.pack(fill="x", pady=(14, 8))
        self.model_menu = ctk.CTkOptionMenu(
            menu_box, values=["Loading models…"], command=self._model_chosen, height=42, corner_radius=8,
            fg_color=t.SNOW, button_color=t.SNOWFIELD, button_hover_color=t.FROST, text_color=t.INK,
            dropdown_fg_color=t.SNOW, dropdown_hover_color=t.SELECTED, dropdown_text_color=t.INK,
            font=t.font(14), dropdown_font=t.font(13), dynamic_resizing=False, width=636,
            state="disabled")
        self.model_menu.pack(fill="x", padx=2, pady=2)
        self.lbl_model = t.label(msec, "", size=13, color=t.LICHEN, wraplength=640)
        self.lbl_model.pack(anchor="w", fill="x")
        t.divider(col).pack(fill="x")
        self.model_infos = []
        background.run(self, lambda: models.available(key_store.get_api_key()), self._models_loaded)

        # --- Fields ---
        from src.services import fields as fieldmod
        on = [f.label for f in fieldmod.load() if f.enabled]
        sec = self._section(col, "Fields", "Reading: " + ", ".join(on))
        sec.sub.configure(wraplength=480)
        t.secondary_button(sec, "Edit fields", command=on_fields, width=110).pack(side="right")
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

    # --- Model ---
    def _per100(self, info):
        if info.cost is None:
            return "price unknown"
        return f"€{info.cost * 100 * self.eur_rate:.2f} per 100 invoices"

    def _option(self, info):
        tag = f" · {info.tag}" if info.tag else ""
        return f"{info.label}{tag} · {self._per100(info)}"

    def _models_loaded(self, result):
        current = settings.load().get("model") or models.default_model()
        if isinstance(result, Exception) or not result:
            self.model_menu.configure(values=[models.label(current)], state="disabled")
            self.model_menu.set(models.label(current))
            self.lbl_model.configure(text="Couldn't load the list of models (check the API key or internet).")
            return
        self.model_infos = result
        if current not in [m.id for m in result]:
            result.insert(0, models.describe(current))
        self.model_menu.configure(values=[self._option(m) for m in result], state="normal")
        self._select(current)

    def _select(self, model_id):
        info = next((m for m in self.model_infos if m.id == model_id), models.describe(model_id))
        self.model_menu.set(self._option(info))
        bits = [f"Tested on sample invoices: {info.tested} fully correct" if info.tested else "Not tested yet"]
        if info.later:
            cost, when = info.later
            bits.append(f"rises to €{cost * 100 * self.eur_rate:.2f} per 100 on {when.day} {when.strftime('%b %Y')}")
        if info.note:
            bits.append(info.note)
        self.lbl_model.configure(text=" · ".join(bits), text_color=t.LICHEN)

    def _model_chosen(self, option):
        info = self.model_infos[[self._option(m) for m in self.model_infos].index(option)]
        previous = settings.load().get("model") or models.default_model()
        if info.id == previous:
            return
        self.model_menu.configure(state="disabled")
        self.lbl_model.configure(text=f"Checking that {info.label} works with your key…", text_color=t.LICHEN)

        def done(err):
            self.model_menu.configure(state="normal")
            if err:
                self._select(previous)
                self.lbl_model.configure(text=f"{info.label} can't be used: {err} Kept {models.label(previous)}.",
                                         text_color=t.RED)
            else:
                settings.save(model=info.id)
                self._select(info.id)
        background.run(self, lambda: models.probe(key_store.get_api_key(), info.id), done)

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
