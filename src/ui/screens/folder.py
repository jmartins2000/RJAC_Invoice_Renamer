"""One folder (project): its invoices, runs, filename settings and destination."""
import os
from tkinter import filedialog

import customtkinter as ctk

from src.services import fields as fieldmod
from src.services import history, models, settings
from src.services.excel_exporter import ExcelExporter
from src.ui import background, icons, theme as t
from src.ui.screens.home import nice_date, nice_path
from src.ui.util import EXAMPLE, EXAMPLE_ORIGINAL, shorten
from src.ui.table import InvoiceTable


class FolderScreen(ctk.CTkFrame):
    def __init__(self, master, path, on_back, on_review, on_customize, eur_rate=0.92):
        super().__init__(master, fg_color=t.SNOW, corner_radius=0)
        self.path, self.on_review, self.eur_rate = path, on_review, eur_rate
        history.add_project(path)
        self.project = history.project(path) or {"dest_folder": None}
        self.fields = [f for f in fieldmod.load() if f.enabled]
        self.new = None

        bar = ctk.CTkFrame(self, fg_color=t.SNOW, corner_radius=0, height=64)
        bar.pack(fill="x")
        ctk.CTkButton(bar, text="", image=icons.line_icon("arrow_left", color=t.c(t.INK)), width=34, height=34,
                      corner_radius=8, fg_color=t.SNOW, hover_color=t.SNOWFIELD, border_width=1,
                      border_color=t.FROST, command=on_back).pack(side="left", padx=(24, 14), pady=14)
        info = ctk.CTkFrame(bar, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)
        t.label(info, os.path.basename(path) or path, size=15, weight="bold").pack(anchor="w")
        t.label(info, nice_path(path, 4), size=12, color=t.LICHEN).pack(anchor="w")
        self.btn_main = t.primary_button(bar, "Checking for new PDFs…", command=self._review, height=38, size=13,
                                         state="disabled")
        self.btn_main.pack(side="right", padx=(10, 24))
        self.btn_export = t.secondary_button(bar, "Export to Excel", command=self._export)
        self.btn_export.pack(side="right")
        t.divider(self).pack(fill="x")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=32, pady=(24, 24))

        side = ctk.CTkFrame(body, fg_color="transparent", width=290)
        side.pack(side="right", fill="y", padx=(28, 0))
        side.pack_propagate(False)
        main = ctk.CTkFrame(body, fg_color="transparent")
        main.pack(side="left", fill="both", expand=True)

        # --- Invoices ---
        head = ctk.CTkFrame(main, fg_color="transparent")
        head.pack(fill="x", pady=(0, 10))
        self.lbl_count = t.eyebrow(head, "")
        self.lbl_count.pack(side="left")
        t.link_button(head, "Open in review", command=lambda: self.on_review(self.path, False)).pack(side="right")
        self.table = InvoiceTable(main, [f for f in self.fields if f.in_excel][:5], extra=("_file", "_status"))
        self.table.pack(fill="both", expand=True)
        rows = history.query(folder=path)
        self.table.set_rows(rows)
        total = sum(r["values"].get("total_value") or 0 for r in rows
                    if isinstance(r["values"].get("total_value"), (int, float)))
        self.lbl_count.configure(text=f"{len(rows)} invoice{'s' if len(rows) != 1 else ''} · total {total:,.2f}")
        self.empty = None
        if not rows:
            self.empty = t.label(main, "No invoices read in this folder yet.", size=14, color=t.LICHEN)
            self.empty.place(relx=0.5, rely=0.5, anchor="center")
        t.label(main, "Double-click a row to open the PDF.", size=12, color=t.LICHEN).pack(anchor="w", pady=(8, 0))

        # --- Side: runs ---
        t.eyebrow(side, "Runs").pack(anchor="w")
        runs = history.runs(path)
        if not runs:
            t.label(side, "None yet", size=13, color=t.LICHEN).pack(anchor="w", pady=(8, 0))
        for r in runs[:6]:
            row = ctk.CTkFrame(side, fg_color="transparent")
            row.pack(fill="x", pady=(8, 0))
            t.label(row, nice_date(r["started_at"]), size=13).pack(side="left")
            what = f"{r['gemini_reads']} read · €{(r['cost_usd'] or 0) * eur_rate:.2f}"
            if r["renamed"]:
                what += f" · {r['renamed']} renamed"
            t.label(row, what, size=13, color=t.LICHEN).pack(side="right")
        if len(runs) > 6:
            t.label(side, f"+ {len(runs) - 6} earlier", size=12, color=t.LICHEN).pack(anchor="w", pady=(6, 0))
        t.divider(side).pack(fill="x", pady=20)

        # --- Side: filename & fields ---
        t.eyebrow(side, "Filename & fields").pack(anchor="w")
        prefs = settings.load()
        example = dict(EXAMPLE)
        for f in self.fields:
            example.setdefault(f.key, f.label)
        name = fieldmod.build_filename(example, EXAMPLE_ORIGINAL, self.fields,
                                       fieldmod.filename_keys(self.fields, prefs.get("filename_original")),
                                       prefs.get("separator") or fieldmod.DEFAULT_SEPARATOR)
        ctk.CTkLabel(side, text=name or "", font=t.mono(12), text_color=t.EVERGREEN, anchor="w", justify="left",
                     wraplength=280).pack(anchor="w", fill="x", pady=(8, 2))
        t.link_button(side, "Customize", command=on_customize).pack(anchor="w")
        t.divider(side).pack(fill="x", pady=20)

        # --- Side: destination ---
        t.eyebrow(side, "Renamed files go to").pack(anchor="w")
        self.lbl_dest = t.label(side, "", size=13, wraplength=280)
        self.lbl_dest.pack(anchor="w", fill="x", pady=(8, 2))
        t.link_button(side, "Change", command=self._change_dest).pack(anchor="w")
        self._show_dest()
        self.on_back = on_back
        ctk.CTkButton(side, text="Remove from the list", height=28, width=0, corner_radius=6,
                      fg_color="transparent", hover_color=t.RED_BG, text_color=t.LICHEN, font=t.font(12),
                      command=self._remove).pack(side="bottom", anchor="w")

        if os.path.isdir(path):
            background.run(self, lambda: history.new_pdfs(path), self._new_counted)
        else:
            self.btn_main.configure(text="Folder not found")

    def destination(self):
        return self.project.get("dest_folder") or self.path

    def _show_dest(self):
        d = self.project.get("dest_folder")
        self.lbl_dest.configure(text=shorten(d, 44) if d else "This folder (renamed in place)")

    def _change_dest(self):
        folder = filedialog.askdirectory(title="Where should renamed files go?", initialdir=self.destination())
        if folder:
            history.set_destination(self.path, folder)
            self.project["dest_folder"] = None if os.path.abspath(folder) == self.path else folder
            self._show_dest()

    def _new_counted(self, new):
        if isinstance(new, Exception):
            new = []
        self.new = new
        n = len(new)
        if n:
            mid = settings.load().get("model") or models.default_model()
            cost = models.cost_per_invoice(mid)
            self.btn_main.configure(text=f"Read {n} new PDF{'s' if n != 1 else ''}", state="normal")
            if cost:
                self.btn_main.configure(text=f"Read {n} new PDF{'s' if n != 1 else ''} · ~€{max(0.01, n * cost * self.eur_rate):.2f}")
        else:
            self.btn_main.configure(text="Review folder", state="normal")

    def _remove(self):
        from tkinter import messagebox
        if messagebox.askyesno("Remove folder", f"Remove \"{os.path.basename(self.path)}\" from your folders?\n\n"
                               "No files are deleted, and invoices already read stay remembered (they won't be "
                               "paid for again if you add the folder back)."):
            history.remove_project(self.path)
            self.on_back()

    def _review(self):
        self.on_review(self.path, bool(self.new))

    def _export(self):
        rows = history.query(folder=self.path)
        if not rows:
            return
        path = filedialog.asksaveasfilename(title="Save spreadsheet", defaultextension=".xlsx",
                                            initialdir=self.destination(),
                                            initialfile=f"{os.path.basename(self.path)}.xlsx",
                                            filetypes=[("Excel", "*.xlsx")])
        if path:
            ok = ExcelExporter.export(rows, [f for f in fieldmod.load() if f.enabled and f.in_excel], path)
            self.btn_export.configure(text="✓ Exported" if ok else "Export failed")
