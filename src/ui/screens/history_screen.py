"""History: every invoice read on this computer, filterable by period and folder, exportable."""
import datetime
import os
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, ttk

import customtkinter as ctk

from src.services import fields as fieldmod
from src.services import history
from src.services.excel_exporter import ExcelExporter
from src.ui import icons, theme as t


def quarter_bounds(year, q):
    start = datetime.date(year, 3 * (q - 1) + 1, 1)
    end = (datetime.date(year + (q == 4), 1 if q == 4 else 3 * q + 1, 1) - datetime.timedelta(days=1))
    return start.isoformat(), end.isoformat()


def period_options():
    """[(label, (start, end))] newest first."""
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


def open_file(path):
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class HistoryScreen(ctk.CTkFrame):
    def __init__(self, master, on_back, on_open_folder):
        super().__init__(master, fg_color=t.SNOW, corner_radius=0)
        self.on_open_folder = on_open_folder
        self.fields = [f for f in fieldmod.load() if f.enabled and f.in_excel]
        self.rows = []

        bar = ctk.CTkFrame(self, fg_color=t.SNOW, corner_radius=0, height=62)
        bar.pack(fill="x")
        ctk.CTkButton(bar, text="", image=icons.line_icon("arrow_left"), width=34, height=34,
                      corner_radius=8, fg_color=t.SNOW, hover_color=t.SNOWFIELD, border_width=1,
                      border_color=t.FROST, command=on_back).pack(side="left", padx=(24, 14), pady=14)
        t.label(bar, "History", size=15, weight="bold").pack(side="left")
        self.btn_export = t.primary_button(bar, "Export to Excel", command=self._export, height=38, size=13)
        self.btn_export.pack(side="right", padx=(10, 24))
        t.secondary_button(bar, "Excel from a folder…", command=self._from_folder).pack(side="right")
        t.divider(self).pack(fill="x")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=32, pady=(20, 24))

        filters = ctk.CTkFrame(body, fg_color="transparent")
        filters.pack(fill="x")
        self.periods = period_options()
        self.folders = history.folders()
        menu_style = dict(height=36, corner_radius=8, fg_color=t.SNOWFIELD, button_color=t.SNOWFIELD,
                          button_hover_color=t.FROST, text_color=t.INK, dropdown_fg_color=t.SNOW,
                          dropdown_hover_color=t.SELECTED, dropdown_text_color=t.INK, font=t.font(13),
                          dropdown_font=t.font(13), dynamic_resizing=False)
        t.label(filters, "Invoice date", size=12, color=t.LICHEN).pack(side="left", padx=(0, 8))
        self.m_period = ctk.CTkOptionMenu(filters, values=[p[0] for p in self.periods], width=230,
                                          command=lambda _: self._load(), **menu_style)
        self.m_period.pack(side="left", padx=(0, 22))
        t.label(filters, "Folder", size=12, color=t.LICHEN).pack(side="left", padx=(0, 8))
        from src.ui.screens.setup import shorten
        self.folder_labels = ["All folders"] + [shorten(f, 48) for f in self.folders]
        self.m_folder = ctk.CTkOptionMenu(filters, values=self.folder_labels, width=340,
                                          command=lambda _: self._load(), **menu_style)
        self.m_folder.pack(side="left")
        self.lbl_summary = t.label(filters, "", size=13, color=t.LICHEN)
        self.lbl_summary.pack(side="right")

        # Table
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("Hist.Treeview", background=t.SNOW, fieldbackground=t.SNOW, foreground=t.INK,
                        rowheight=30, borderwidth=0, font=(t.SANS, 12))
        style.configure("Hist.Treeview.Heading", background=t.SNOWFIELD, foreground=t.LICHEN, relief="flat",
                        font=(t.SANS, 11, "bold"), padding=(8, 6))
        style.map("Hist.Treeview", background=[("selected", t.SELECTED)], foreground=[("selected", t.INK)])
        style.map("Hist.Treeview.Heading", background=[("active", t.FROST)])

        table = ctk.CTkFrame(body, fg_color=t.SNOW, corner_radius=10, border_width=1, border_color=t.FROST)
        table.pack(fill="both", expand=True, pady=(16, 0))
        self.columns = [f.key for f in self.fields] + ["_file", "_folder"]
        self.tree = ttk.Treeview(table, columns=self.columns, show="headings", style="Hist.Treeview")
        for f in self.fields:
            self.tree.heading(f.key, text=f.label, command=lambda k=f.key: self._sort(k))
            self.tree.column(f.key, width=110 if f.type in ("date", "number") else 170,
                             anchor="e" if f.type == "number" else "w", stretch=f.type == "text")
        self.tree.heading("_file", text="File", command=lambda: self._sort("_file"))
        self.tree.column("_file", width=220, anchor="w")
        self.tree.heading("_folder", text="Folder", command=lambda: self._sort("_folder"))
        self.tree.column("_folder", width=160, anchor="w")
        sb = ctk.CTkScrollbar(table, command=self.tree.yview, button_color=t.FROST,
                              button_hover_color=t.FIELD_BORDER)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 4), pady=6)
        self.tree.pack(fill="both", expand=True, padx=(6, 0), pady=6)
        self.tree.tag_configure("odd", background="#FAFBFA")
        self.tree.bind("<Double-1>", self._open_selected)

        self.empty = t.label(body, "", size=14, color=t.LICHEN)
        t.label(body, "Double-click a row to open the PDF.", size=12, color=t.LICHEN).pack(anchor="w", pady=(8, 0))
        self._sort_key, self._sort_rev = None, False
        self._load()

    def _load(self):
        start, end = dict(self.periods)[self.m_period.get()]
        idx = self.folder_labels.index(self.m_folder.get())
        folder = self.folders[idx - 1] if idx > 0 else None
        self.rows = history.query(start, end, folder)
        self._render()

    def _cell(self, row, key):
        if key == "_file":
            return row["file_name"]
        if key == "_folder":
            return os.path.basename(row["folder"] or "")
        f = next(x for x in self.fields if x.key == key)
        return fieldmod.display_value(f, row["values"].get(key))

    def _render(self):
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self.rows):
            self.tree.insert("", "end", iid=str(i), values=[self._cell(r, c) for c in self.columns],
                             tags=("odd",) if i % 2 else ())
        total = sum(r["values"].get("total_value") or 0 for r in self.rows
                    if isinstance(r["values"].get("total_value"), (int, float)))
        n = len(self.rows)
        self.lbl_summary.configure(text=f"{n} invoice{'s' if n != 1 else ''} · total {total:,.2f}")
        if not n:
            self.empty.configure(text="No invoices here yet. Invoices you read are added automatically.")
            self.empty.place(relx=0.5, rely=0.45, anchor="center")
        else:
            self.empty.place_forget()

    def _sort(self, key):
        self._sort_rev = not self._sort_rev if self._sort_key == key else False
        self._sort_key = key

        def k(r):
            v = r["values"].get(key) if not key.startswith("_") else self._cell(r, key)
            return (v is None or v == "", v if isinstance(v, (int, float)) else str(v or "").lower())
        self.rows.sort(key=k, reverse=self._sort_rev)
        self._render()

    def _open_selected(self, _e):
        sel = self.tree.selection()
        if sel:
            r = self.rows[int(sel[0])]
            path = os.path.join(r["folder"], r["file_name"])
            if os.path.exists(path):
                open_file(path)
            else:
                tk.messagebox.showinfo("File not found", f"This file is no longer at:\n{path}")

    def _export(self):
        if not self.rows:
            return
        name = "invoices.xlsx"
        period = self.m_period.get()
        if period != "All time":
            name = f"invoices {period.split('(')[-1].rstrip(')')}.xlsx"
        path = filedialog.asksaveasfilename(title="Save spreadsheet", defaultextension=".xlsx", initialfile=name,
                                            filetypes=[("Excel", "*.xlsx")])
        if path:
            ok = ExcelExporter.export(self.rows, self.fields, path)
            self.btn_export.configure(text="✓ Exported" if ok else "Export failed")

    def _from_folder(self):
        folder = filedialog.askdirectory(title="Choose a folder of invoices to build the Excel from")
        if folder:
            self.on_open_folder(folder)
