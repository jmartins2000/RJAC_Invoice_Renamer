"""All invoices: every invoice read on this computer, by invoice-date period and folder."""
import datetime
import os
from tkinter import filedialog

import customtkinter as ctk

from src.services import fields as fieldmod
from src.services import history
from src.services.excel_exporter import ExcelExporter
from src.ui import icons, theme as t
from src.ui.table import InvoiceTable
from src.ui.util import shorten


def quarter_bounds(year, q):
    start = datetime.date(year, 3 * (q - 1) + 1, 1)
    end = datetime.date(year + (q == 4), 1 if q == 4 else 3 * q + 1, 1) - datetime.timedelta(days=1)
    return start.isoformat(), end.isoformat()


def period_options():
    """[(label, (start, end))]: recent periods first, then every quarter of every year with invoices."""
    today = datetime.date.today()
    q = (today.month - 1) // 3 + 1
    lq_year, lq = (today.year, q - 1) if q > 1 else (today.year - 1, 4)
    opts = [("All time", (None, None)),
            (f"This quarter (Q{q} {today.year})", quarter_bounds(today.year, q)),
            (f"Last quarter (Q{lq} {lq_year})", quarter_bounds(lq_year, lq)),
            (f"This year ({today.year})", (f"{today.year}-01-01", f"{today.year}-12-31")),
            (f"Last year ({today.year - 1})", (f"{today.year - 1}-01-01", f"{today.year - 1}-12-31"))]
    for y in history.years():
        y = int(y)
        opts.append((f"{y} (whole year)", (f"{y}-01-01", f"{y}-12-31")))
        for qq in (4, 3, 2, 1):
            opts.append((f"Q{qq} {y}", quarter_bounds(y, qq)))
    seen, out = set(), []
    for label, rng in opts:
        if label not in seen:
            seen.add(label)
            out.append((label, rng))
    return out


class HistoryScreen(ctk.CTkFrame):
    def __init__(self, master, on_back, on_open_folder):
        super().__init__(master, fg_color=t.SNOW, corner_radius=0)
        self.on_open_folder = on_open_folder
        self.fields = [f for f in fieldmod.load() if f.enabled and f.in_excel]

        bar = ctk.CTkFrame(self, fg_color=t.SNOW, corner_radius=0, height=62)
        bar.pack(fill="x")
        ctk.CTkButton(bar, text="", image=icons.line_icon("arrow_left"), width=34, height=34,
                      corner_radius=8, fg_color=t.SNOW, hover_color=t.SNOWFIELD, border_width=1,
                      border_color=t.FROST, command=on_back).pack(side="left", padx=(24, 14), pady=14)
        t.label(bar, "All invoices", size=15, weight="bold").pack(side="left")
        self.btn_export = t.primary_button(bar, "Export to Excel", command=self._export, height=38, size=13)
        self.btn_export.pack(side="right", padx=(10, 24))
        t.secondary_button(bar, "Excel from any folder…", command=self._from_folder).pack(side="right")
        t.divider(self).pack(fill="x")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=32, pady=(20, 24))
        filters = ctk.CTkFrame(body, fg_color="transparent")
        filters.pack(fill="x")
        self.periods = period_options()
        self.folders = history.folders()
        menu = dict(height=36, corner_radius=8, fg_color=t.SNOWFIELD, button_color=t.SNOWFIELD,
                    button_hover_color=t.FROST, text_color=t.INK, dropdown_fg_color=t.SNOW,
                    dropdown_hover_color=t.SELECTED, dropdown_text_color=t.INK, font=t.font(13),
                    dropdown_font=t.font(13), dynamic_resizing=False)
        t.label(filters, "Invoice date", size=12, color=t.LICHEN).pack(side="left", padx=(0, 8))
        self.m_period = ctk.CTkOptionMenu(filters, values=[p[0] for p in self.periods], width=230,
                                          command=lambda _: self._load(), **menu)
        self.m_period.pack(side="left", padx=(0, 22))
        t.label(filters, "Folder", size=12, color=t.LICHEN).pack(side="left", padx=(0, 8))
        self.folder_labels = ["All folders"] + [shorten(os.path.basename(f) or f, 40) for f in self.folders]
        self.m_folder = ctk.CTkOptionMenu(filters, values=self.folder_labels, width=260,
                                          command=lambda _: self._load(), **menu)
        self.m_folder.pack(side="left")
        self.lbl_summary = t.label(filters, "", size=13, color=t.LICHEN)
        self.lbl_summary.pack(side="right")

        self.table = InvoiceTable(body, self.fields, extra=("_folder", "_file", "_status"))
        self.table.pack(fill="both", expand=True, pady=(16, 0))
        self.empty = t.label(body, "", size=14, color=t.LICHEN)
        t.label(body, "Double-click a row to open the PDF.", size=12, color=t.LICHEN).pack(anchor="w", pady=(8, 0))
        self._load()

    def _load(self):
        start, end = dict(self.periods)[self.m_period.get()]
        idx = self.folder_labels.index(self.m_folder.get())
        folder = self.folders[idx - 1] if idx > 0 else None
        rows = history.query(start, end, folder)
        self.table.set_rows(rows)
        total = sum(r["values"].get("total_value") or 0 for r in rows
                    if isinstance(r["values"].get("total_value"), (int, float)))
        self.lbl_summary.configure(text=f"{len(rows)} invoice{'s' if len(rows) != 1 else ''} · total {total:,.2f}")
        if rows:
            self.empty.place_forget()
        else:
            self.empty.configure(text="No invoices for this selection.")
            self.empty.place(relx=0.5, rely=0.5, anchor="center")

    def _export(self):
        rows = self.table.rows
        if not rows:
            return
        period = self.m_period.get()
        name = "invoices.xlsx" if period == "All time" else f"invoices {period.split('(')[-1].rstrip(')')}.xlsx"
        path = filedialog.asksaveasfilename(title="Save spreadsheet", defaultextension=".xlsx", initialfile=name,
                                            filetypes=[("Excel", "*.xlsx")])
        if path:
            ok = ExcelExporter.export(rows, self.fields, path)
            self.btn_export.configure(text="✓ Exported" if ok else "Export failed")

    def _from_folder(self):
        folder = filedialog.askdirectory(title="Choose a folder of invoices to build the Excel from")
        if folder:
            history.add_project(folder)
            self.on_open_folder(os.path.abspath(folder))
