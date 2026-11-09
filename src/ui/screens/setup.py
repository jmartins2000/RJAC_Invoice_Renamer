"""Home screen: pick folders and the filename format."""
import os
from tkinter import filedialog

import customtkinter as ctk

from src.services import fields as fieldmod
from src.services import models, settings
from src.ui import icons, theme as t

EXAMPLE = {"date": "2026-10-06", "total_value": 60000.0, "invoice_number": "FT A/29",
           "supplier": "Quociente Invencível Lda", "supplier_nif": "517875845", "net_amount": 48780.49,
           "vat_amount": 11219.51, "vat_rate": "23%", "currency": "EUR"}
EXAMPLE_ORIGINAL = "Fatura FT A-29.pdf"


def shorten(text, limit=52):
    """Middle-ellipsis for long paths."""
    return text if len(text) <= limit else f"{text[:limit // 2 - 1]}…{text[-(limit // 2):]}"


def count_pdfs(folder):
    try:
        return sum(1 for f in os.listdir(folder) if f.lower().endswith(".pdf") and not f.startswith("."))
    except OSError:
        return 0


class FolderCard(ctk.CTkFrame):
    """Clickable card showing a folder choice."""

    def __init__(self, master, filled, icon_name, action_text, command):
        super().__init__(master, corner_radius=12, border_width=1, border_color=t.FROST,
                         fg_color=t.SNOWFIELD if filled else t.SNOW)
        self.command = command
        self.action = t.label(self, action_text, size=13, color=t.EVERGREEN, weight="bold")
        self.action.pack(side="right", padx=20)
        self.icon = ctk.CTkLabel(self, text="", image=icons.tile(icon_name, filled))
        self.icon.pack(side="left", padx=(20, 16), pady=20)
        text = ctk.CTkFrame(self, fg_color="transparent")
        text.pack(side="left", fill="x", expand=True)
        self.title = t.label(text, "", size=15, weight="bold")
        self.title.pack(anchor="w", fill="x")
        self.sub = t.label(text, "", size=13, color=t.LICHEN)
        self.sub.pack(anchor="w", fill="x", pady=(2, 0))
        for w in (self, self.icon, text, self.title, self.sub, self.action):
            w.bind("<Button-1>", lambda _: self.command())
            w.configure(cursor=t.HAND)

    def set(self, title, sub):
        self.title.configure(text=title)
        self.sub.configure(text=sub)


class SetupScreen(ctk.CTkFrame):
    def __init__(self, master, on_start, on_settings, on_history, eur_rate=0.92):
        super().__init__(master, fg_color=t.SNOW, corner_radius=0)
        self.on_start = on_start
        self.eur_rate = eur_rate
        prefs = settings.load()
        self.fields = fieldmod.load()
        self.include_original = bool(prefs.get("filename_original"))
        self.separator = prefs.get("separator") or fieldmod.DEFAULT_SEPARATOR
        self.source = prefs["last_source"] if prefs["last_source"] and os.path.isdir(prefs["last_source"]) else None
        self.dest = None

        # --- Top bar ---
        bar = ctk.CTkFrame(self, fg_color=t.SNOW, corner_radius=0, height=66)
        bar.pack(fill="x")
        ctk.CTkLabel(bar, text="", image=icons.logo(26)).pack(side="left", padx=(32, 12), pady=18)
        t.label(bar, "Invoice Renamer", size=15, weight="bold").pack(side="left")
        ctk.CTkButton(bar, text="Settings", image=icons.line_icon("gear", 16, stroke=1.8), compound="left",
                      command=on_settings, height=36, width=0, corner_radius=8, fg_color=t.SNOW,
                      hover_color=t.SNOWFIELD, border_width=1, border_color=t.FROST, text_color=t.INK,
                      font=t.font(13)).pack(side="right", padx=(10, 32))
        t.secondary_button(bar, "History", command=on_history, height=36).pack(side="right")
        self.update_slot = ctk.CTkFrame(bar, fg_color="transparent", width=1, height=36)
        self.update_slot.pack(side="right")
        t.divider(self).pack(fill="x")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=64, pady=(44, 36))

        ctk.CTkLabel(body, text="Rename a folder of invoices", font=t.display(30), text_color=t.INK,
                     anchor="w").pack(anchor="w")
        t.label(body, "Gemini reads each PDF, you check the values, then everything is renamed in one go.",
                size=15, color=t.LICHEN).pack(anchor="w", pady=(6, 32))

        footer = ctk.CTkFrame(body, fg_color="transparent")
        footer.pack(side="bottom", fill="x")
        t.divider(footer).pack(fill="x", pady=(0, 24))
        self.lbl_estimate = t.label(footer, "", size=13, color=t.LICHEN)
        self.lbl_estimate.pack(side="left")
        self.btn_start = t.primary_button(footer, "Read invoices", command=self._start, width=200, height=48,
                                          size=15, image=icons.line_icon("arrow_right", 18, "#FFFFFF"),
                                          compound="right")
        self.btn_start.pack(side="right")

        cols = ctk.CTkFrame(body, fg_color="transparent")
        cols.pack(fill="both", expand=True)
        left = ctk.CTkFrame(cols, fg_color="transparent", width=480)
        left.pack(side="left", fill="y", anchor="n")
        left.pack_propagate(False)
        right = ctk.CTkFrame(cols, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, padx=(48, 0), anchor="n")

        # --- Folders ---
        t.eyebrow(left, "1 · Invoices folder").pack(anchor="w", pady=(0, 10))
        self.card_source = FolderCard(left, True, "folder", "Choose…", self._choose_source)
        self.card_source.pack(fill="x")
        t.eyebrow(left, "2 · Save renamed files to").pack(anchor="w", pady=(28, 10))
        self.card_dest = FolderCard(left, False, "folder_down", "Choose…", self._choose_dest)
        self.card_dest.pack(fill="x")
        t.label(left, "Invoices read before are recognised and not sent to Gemini again.",
                size=13, color=t.LICHEN, wraplength=470).pack(anchor="w", pady=(20, 0))

        # --- Filename builder ---
        t.eyebrow(right, "3 · New filename").pack(anchor="w", pady=(0, 10))
        card = ctk.CTkFrame(right, fg_color=t.SNOW, corner_radius=12, border_width=1, border_color=t.FROST)
        card.pack(fill="x")
        self.chips_box = ctk.CTkFrame(card, fg_color="transparent")
        self.chips_box.pack(fill="x", padx=24, pady=(24, 0))

        sep_row = ctk.CTkFrame(card, fg_color="transparent")
        sep_row.pack(fill="x", padx=24, pady=(6, 0))
        t.label(sep_row, "Separator", size=13, color=t.LICHEN).pack(side="left", padx=(0, 12))
        self.sep_labels = {" ~ ": "~", " - ": "-", " _ ": "_", " ": "Space"}
        self.sep_menu = ctk.CTkSegmentedButton(
            sep_row, values=list(self.sep_labels.values()), command=self._set_separator, height=30,
            font=t.font(13), fg_color=t.SNOWFIELD, selected_color=t.EVERGREEN,
            selected_hover_color=t.EVERGREEN_HOVER, unselected_color=t.SNOWFIELD,
            unselected_hover_color=t.FROST, text_color=t.INK, corner_radius=8)
        self.sep_menu.pack(side="left")
        self.sep_menu.set(self.sep_labels.get(self.separator, "~"))

        ex = ctk.CTkFrame(card, fg_color=t.SNOWFIELD, corner_radius=10)
        ex.pack(fill="x", padx=24, pady=(16, 0))
        t.label(ex, "Example", size=12, color=t.LICHEN).pack(anchor="w", padx=20, pady=(16, 6))
        self.lbl_example = ctk.CTkLabel(ex, text="", font=t.mono(14), text_color=t.EVERGREEN,
                                        anchor="w", justify="left", wraplength=380)
        self.lbl_example.pack(anchor="w", fill="x", padx=20, pady=(0, 16))
        t.label(card, "Click a field to add or remove it. Add more fields (like NIF or VAT) in Settings.",
                size=13, color=t.LICHEN, wraplength=400).pack(anchor="w", fill="x", padx=24, pady=(18, 24))
        right.bind("<Configure>", lambda e: self.lbl_example.configure(wraplength=max(200, e.width - 90)))

        self._build_chips()
        self._refresh()

    # --- Update notice in the top bar ---
    def show_update(self, info, on_click):
        for w in self.update_slot.winfo_children():
            w.destroy()
        ctk.CTkButton(self.update_slot, text=f"Update to {info.version}", command=on_click, height=36,
                      width=0, corner_radius=8, fg_color=t.SELECTED, hover_color="#DCE9DE",
                      text_color=t.EVERGREEN, font=t.font(13, "bold")).pack(side="right", padx=(0, 10))

    # --- Filename chips ---
    def _build_chips(self):
        for w in self.chips_box.winfo_children():
            w.destroy()
        self.chips = {}
        items = [(f.key, f.label) for f in self.fields if f.enabled] + [(fieldmod.ORIGINAL, "Original name")]
        row, width = None, 0
        for key, text in items:
            if row is None or width > 330:
                row = ctk.CTkFrame(self.chips_box, fg_color="transparent")
                row.pack(anchor="w")
                width = 0
            b = ctk.CTkButton(row, text=text, height=34, width=0, corner_radius=17, font=t.font(13),
                              border_width=1, command=lambda k=key: self._toggle(k))
            b.pack(side="left", padx=(0, 8), pady=(0, 8))
            width += len(text) * 8 + 40
            self.chips[key] = b

    def _is_on(self, key):
        if key == fieldmod.ORIGINAL:
            return self.include_original
        return next(f.in_filename for f in self.fields if f.key == key)

    def _toggle(self, key):
        if key == fieldmod.ORIGINAL:
            self.include_original = not self.include_original
        else:
            for f in self.fields:
                if f.key == key:
                    f.in_filename = not f.in_filename
        if not fieldmod.filename_keys(self.fields, self.include_original):
            self._toggle(key)  # keep at least one
            return
        fieldmod.save(self.fields)
        settings.save(filename_original=self.include_original)
        self._refresh()

    def _set_separator(self, label):
        self.separator = next(k for k, v in self.sep_labels.items() if v == label)
        settings.save(separator=self.separator)
        self._refresh()

    # --- Actions ---
    def _choose_source(self):
        folder = filedialog.askdirectory(title="Choose the folder with your invoices",
                                         initialdir=self.source or os.path.expanduser("~"))
        if folder:
            self.source = folder
            settings.save(last_source=folder)
            self._refresh()

    def _choose_dest(self):
        folder = filedialog.askdirectory(title="Choose where to save the renamed files",
                                         initialdir=self.dest or self.source or os.path.expanduser("~"))
        if folder:
            self.dest = folder
            self._refresh()

    def _start(self):
        if self.source and count_pdfs(self.source):
            self.on_start(self.source, self.dest or self.source)
        else:
            self._choose_source()

    def _refresh(self):
        n = count_pdfs(self.source) if self.source else 0
        if self.source:
            self.card_source.set(shorten(os.path.basename(self.source) or self.source, 34),
                                 f"{shorten(self.source, 34)} · {n} PDF{'s' if n != 1 else ''}")
            self.card_source.action.configure(text="Change")
        else:
            self.card_source.set("Choose a folder", "The folder with the invoice PDFs")
        if self.dest and self.dest != self.source:
            self.card_dest.set(shorten(os.path.basename(self.dest) or self.dest, 34), shorten(self.dest, 52))
        else:
            self.card_dest.set("Same folder", "Renamed files go next to the originals")

        for key, b in self.chips.items():
            on = self._is_on(key)
            label = "Original name" if key == fieldmod.ORIGINAL else next(f.label for f in self.fields if f.key == key)
            b.configure(text=label if on else f"+ {label}",
                        fg_color=t.EVERGREEN if on else t.SNOW,
                        hover_color=t.EVERGREEN_HOVER if on else t.SNOWFIELD,
                        border_color=t.EVERGREEN if on else t.FIELD_BORDER,
                        text_color=t.SNOW if on else t.LICHEN)
        example = dict(EXAMPLE)
        for f in self.fields:
            example.setdefault(f.key, f.label)
        name = fieldmod.build_filename(example, EXAMPLE_ORIGINAL, self.fields,
                                       fieldmod.filename_keys(self.fields, self.include_original), self.separator)
        self.lbl_example.configure(text=name or "")

        mid = settings.load().get("model") or models.default_model()
        if n:
            self.btn_start.configure(text=f"Read {n} invoice{'s' if n != 1 else ''}", state="normal")
            cost = models.cost_per_invoice(mid)
            est = f"New invoices: about €{max(0.01, n * cost * self.eur_rate):.2f} for {n} · " if cost else ""
            self.lbl_estimate.configure(text=f"{est}{models.label(mid)}")
        else:
            self.btn_start.configure(text="Choose a folder")
            self.lbl_estimate.configure(text="No PDFs found yet" if self.source else "")
