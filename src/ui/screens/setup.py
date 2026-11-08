"""Home screen: pick folders and the filename format."""
import os
from tkinter import filedialog

import customtkinter as ctk

from src.services import settings
from src.ui import icons, theme as t

FIELDS = [("date", "Date"), ("value", "Total"), ("invoice_number", "Invoice no."),
          ("supplier", "Supplier"), ("original", "Original name")]
EXAMPLE = {"date": "2026.10.06", "value": "60000.00", "invoice_number": "FT A_29",
           "supplier": "Quociente Invencível Lda", "original": "Fatura FT A-29"}


def shorten(text, limit=52):
    """Middle-ellipsis for long paths: 'C:\\Users\\…\\Faturas'."""
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
            w.configure(cursor="hand2")

    def set(self, title, sub):
        self.title.configure(text=title)
        self.sub.configure(text=sub)


class SetupScreen(ctk.CTkFrame):
    def __init__(self, master, on_start, on_settings, eur_rate=0.92):
        super().__init__(master, fg_color=t.SNOW, corner_radius=0)
        self.on_start = on_start
        self.eur_rate = eur_rate
        prefs = settings.load()
        self.fields = dict(prefs["filename_fields"])
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
                      font=t.font(13)).pack(side="right", padx=32)
        self.update_slot = ctk.CTkFrame(bar, fg_color="transparent", width=1, height=36)
        self.update_slot.pack(side="right")
        t.divider(self).pack(fill="x")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=64, pady=(44, 36))

        # --- Heading ---
        ctk.CTkLabel(body, text="Rename a folder of invoices", font=t.display(30), text_color=t.INK,
                     anchor="w").pack(anchor="w")
        t.label(body, "Gemini reads each PDF, you check the values, then everything is renamed in one go.",
                size=15, color=t.LICHEN).pack(anchor="w", pady=(6, 32))

        # --- Footer (packed before columns so it keeps its place at the bottom) ---
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
        left.pack_propagate(False)  # fixed column width; long paths are shortened instead
        right = ctk.CTkFrame(cols, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, padx=(48, 0), anchor="n")

        # --- Folders ---
        t.eyebrow(left, "1 · Invoices folder").pack(anchor="w", pady=(0, 10))
        self.card_source = FolderCard(left, True, "folder", "Choose…", self._choose_source)
        self.card_source.configure(width=480)
        self.card_source.pack(fill="x")
        t.eyebrow(left, "2 · Save renamed files to").pack(anchor="w", pady=(28, 10))
        self.card_dest = FolderCard(left, False, "folder_down", "Choose…", self._choose_dest)
        self.card_dest.pack(fill="x")

        toggle = ctk.CTkFrame(left, fg_color="transparent")
        toggle.pack(anchor="w", pady=(28, 0), fill="x")
        self.delete_var = ctk.BooleanVar(value=prefs["delete_original"])
        t.Toggle(toggle, self.delete_var,
                 command=lambda: settings.save(delete_original=self.delete_var.get())).pack(side="left", padx=(2, 0))
        tt = ctk.CTkFrame(toggle, fg_color="transparent")
        tt.pack(side="left", padx=(14, 0))
        t.label(tt, "Delete the originals after renaming", size=14, weight="normal").pack(anchor="w")
        t.label(tt, "Only after each copy is saved safely", size=13, color=t.LICHEN).pack(anchor="w")

        # --- Filename builder ---
        t.eyebrow(right, "3 · New filename").pack(anchor="w", pady=(0, 10))
        card = ctk.CTkFrame(right, fg_color=t.SNOW, corner_radius=12, border_width=1, border_color=t.FROST)
        card.pack(fill="x")
        chips = ctk.CTkFrame(card, fg_color="transparent")
        chips.pack(fill="x", padx=24, pady=(24, 0))
        self.chips = {}
        rows = [ctk.CTkFrame(chips, fg_color="transparent") for _ in range(2)]
        for r in rows:
            r.pack(anchor="w")
        for i, (key, text) in enumerate(FIELDS):
            b = ctk.CTkButton(rows[i // 4], text=text, height=34, width=0, corner_radius=17, font=t.font(13),
                              border_width=1, command=lambda k=key: self._toggle(k))
            b.pack(side="left", padx=(0, 8), pady=(0, 8))
            self.chips[key] = b
        ex = ctk.CTkFrame(card, fg_color=t.SNOWFIELD, corner_radius=10)
        ex.pack(fill="x", padx=24, pady=(14, 0))
        t.label(ex, "Example", size=12, color=t.LICHEN).pack(anchor="w", padx=20, pady=(16, 6))
        self.lbl_example = ctk.CTkLabel(ex, text="", font=t.mono(14), text_color=t.EVERGREEN,
                                        anchor="w", justify="left", wraplength=380)
        self.lbl_example.pack(anchor="w", fill="x", padx=20, pady=(0, 16))
        t.label(card, "Click a field to add or remove it. You'll be able to correct every value before "
                      "anything is renamed.", size=13, color=t.LICHEN, wraplength=400).pack(
            anchor="w", fill="x", padx=24, pady=(18, 24))
        right.bind("<Configure>", lambda e: self.lbl_example.configure(wraplength=max(200, e.width - 90)))

        self._refresh()

    # --- Update notice in the top bar ---
    def show_update(self, info, on_click):
        for w in self.update_slot.winfo_children():
            w.destroy()
        ctk.CTkButton(self.update_slot, text=f"Update to {info.version}", command=on_click, height=36,
                      width=0, corner_radius=8, fg_color=t.SELECTED, hover_color="#DCE9DE",
                      text_color=t.EVERGREEN, font=t.font(13, "bold")).pack(side="right", padx=(0, 10))

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

    def _toggle(self, key):
        self.fields[key] = not self.fields[key]
        if not any(self.fields.values()):
            self.fields[key] = True  # at least one field
        settings.save(filename_fields=self.fields)
        self._refresh()

    def _start(self):
        if self.source and count_pdfs(self.source):
            self.on_start(self.source, self.dest or self.source, self.delete_var.get(), dict(self.fields))
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
            on = self.fields[key]
            label = dict(FIELDS)[key]
            b.configure(text=label if on else f"+ {label}",
                        fg_color=t.EVERGREEN if on else t.SNOW,
                        hover_color=t.EVERGREEN_HOVER if on else t.SNOWFIELD,
                        border_color=t.EVERGREEN if on else t.FIELD_BORDER,
                        text_color=t.SNOW if on else t.LICHEN)
        parts = [EXAMPLE[k] for k in ("date", "value", "invoice_number", "supplier") if self.fields[k]]
        name = " ".join(parts)
        if self.fields["original"]:
            name = f"{name}_{EXAMPLE['original']}" if name else EXAMPLE["original"]
        self.lbl_example.configure(text=f"{name}.pdf")

        if n:
            self.btn_start.configure(text=f"Read {n} invoice{'s' if n != 1 else ''}", state="normal")
            self.lbl_estimate.configure(text=f"About €{max(0.01, n * 0.0035 * self.eur_rate):.2f} for {n} invoices · Gemini 3.8 Flash")
        else:
            self.btn_start.configure(text="Choose a folder")
            self.lbl_estimate.configure(text="No PDFs found yet" if self.source else "")
