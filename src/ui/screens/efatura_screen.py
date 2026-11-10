"""Compare a client's invoices with their e-Fatura export."""
import os
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from src.services import efatura, periods
from src.services import history
from src.ui import icons, theme as t
from src.ui.feedback_dialog import feedback_button
from src.ui.screens.home import nice_path
from src.ui.table import style as table_style

GROUPS = [
    ("missing", "In e-Fatura, no receipt", "Invoices the AT has for this client with no receipt in the folder.", "AMBER"),
    ("not_in_ef", "Receipt not in e-Fatura", "Receipts in the folder that the AT doesn't have (e.g. no NIF on them).", "AMBER"),
    ("differ", "Values differ", "Found in both, but the date or total doesn't match.", "RED"),
    ("matched", "Matched", "Receipt and e-Fatura agree.", "NEEDLE"),
]


def choose_exports(parent):
    return filedialog.askopenfilenames(
        parent=parent, title="Choose e-Fatura export files (one per month or quarter)",
        filetypes=[("e-Fatura export", "*.csv *.txt"), ("All files", "*.*")])


def import_exports(parent, project):
    """Asks for export files and imports them. Returns True if something was imported."""
    paths = choose_exports(parent)
    if not paths:
        return False
    try:
        n, total = efatura.import_files(project, list(paths))
    except ValueError as e:
        messagebox.showwarning("e-Fatura", str(e))
        return False
    messagebox.showinfo("e-Fatura", f"Read {n} invoice{'s' if n != 1 else ''} from {len(paths)} file"
                                    f"{'s' if len(paths) != 1 else ''}. This client now has {total} e-Fatura "
                                    "invoices (duplicates are ignored).")
    return True


class EfaturaScreen(ctk.CTkFrame):
    def __init__(self, master, project, on_back):
        super().__init__(master, fg_color=t.SNOW, corner_radius=0)
        self.project = project
        self.group = "missing"
        self.result = None

        bar = ctk.CTkFrame(self, fg_color=t.SNOW, corner_radius=0, height=64)
        bar.pack(fill="x")
        ctk.CTkButton(bar, text="", image=icons.line_icon("arrow_left"), width=34, height=34, corner_radius=8,
                      fg_color=t.SNOW, hover_color=t.SNOWFIELD, border_width=1, border_color=t.FROST,
                      command=on_back).pack(side="left", padx=(24, 14), pady=14)
        info = ctk.CTkFrame(bar, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)
        t.label(info, f"e-Fatura · {os.path.basename(project)}", size=15, weight="bold").pack(anchor="w")
        t.label(info, nice_path(project, 4), size=12, color=t.LICHEN).pack(anchor="w")
        t.primary_button(bar, "Export results to Excel", command=self._export, height=38, size=13).pack(
            side="right", padx=(10, 24))
        t.secondary_button(bar, "Import export files…", command=self._import).pack(side="right")
        feedback_button(bar).pack(side="right", padx=(0, 8))
        t.divider(self).pack(fill="x")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=32, pady=(18, 22))

        head = ctk.CTkFrame(body, fg_color="transparent")
        head.pack(fill="x")
        self.periods = periods.options(history.years(project))
        self.periods = [p for p in self.periods if p[0] != periods.CUSTOM]
        self.m_period = ctk.CTkOptionMenu(
            head, values=[p[0] for p in self.periods], width=230, height=34, corner_radius=8,
            fg_color=t.SNOWFIELD, button_color=t.SNOWFIELD, button_hover_color=t.FROST, text_color=t.INK,
            dropdown_fg_color=t.SNOW, dropdown_hover_color=t.SELECTED, dropdown_text_color=t.INK,
            font=t.font(13), dropdown_font=t.font(13), dynamic_resizing=False, command=lambda _: self._load())
        self.m_period.pack(side="left")
        self.lbl_count = t.label(head, "", size=13, color=t.LICHEN)
        self.lbl_count.pack(side="right")

        tiles = ctk.CTkFrame(body, fg_color="transparent")
        tiles.pack(fill="x", pady=(16, 12))
        self.tiles = {}
        for i, (key, title, _, color) in enumerate(GROUPS):
            tile = ctk.CTkFrame(tiles, fg_color=t.SNOW, corner_radius=10, border_width=1, border_color=t.FROST,
                                cursor=t.HAND)
            tile.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 10, 0))
            tiles.grid_columnconfigure(i, weight=1, uniform="t")
            num = t.label(tile, "–", size=24, weight="bold", color=getattr(t, color))
            num.pack(anchor="w", padx=16, pady=(12, 0))
            lab = t.label(tile, title, size=12, color=t.LICHEN)
            lab.pack(anchor="w", padx=16, pady=(0, 12))
            for w in (tile, num, lab):
                w.bind("<Button-1>", lambda _e, k=key: self._show(k))
            self.tiles[key] = (tile, num)

        self.lbl_group = t.label(body, "", size=13, color=t.LICHEN, wraplength=900)
        self.lbl_group.pack(anchor="w", pady=(0, 8))

        table_style(self)
        box = ctk.CTkFrame(body, fg_color=t.SNOW, corner_radius=10, border_width=1, border_color=t.FROST)
        box.pack(fill="both", expand=True)
        cols = ("date", "supplier", "nif", "number", "total", "note")
        self.tree = ttk.Treeview(box, columns=cols, show="headings", style="Inv.Treeview")
        for c, title, w, anchor in (("date", "Date", 100, "w"), ("supplier", "Supplier", 220, "w"),
                                    ("nif", "NIF", 100, "w"), ("number", "Document", 220, "w"),
                                    ("total", "Total", 90, "e"), ("note", "Note", 240, "w")):
            self.tree.heading(c, text=title)
            self.tree.column(c, width=w, anchor=anchor, stretch=c in ("supplier", "note"))
        sb = ctk.CTkScrollbar(box, command=self.tree.yview, button_color=t.FROST, button_hover_color=t.FIELD_BORDER)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 4), pady=6)
        self.tree.pack(fill="both", expand=True, padx=(6, 0), pady=6)
        self.tree.tag_configure("odd", background=t.c(t.ROW_ALT))

        self.empty = ctk.CTkLabel(body, text="", font=t.font(14), text_color=t.LICHEN, wraplength=640,
                                  justify="center")
        self._load()

    # --- data ---
    def _period(self):
        return next(p for p in self.periods if p[0] == self.m_period.get())

    def _load(self):
        if not efatura.stored_count(self.project):
            self.result = None
            for _, num in self.tiles.values():
                num.configure(text="–")
            self.tree.delete(*self.tree.get_children())
            self.lbl_count.configure(text="")
            self.empty.configure(text="No e-Fatura data for this client yet.\n\nIn the Portal das Finanças: e-Fatura → "
                                      "Faturação → Adquirente → choose the period → Pesquisar → \"Obter dados para "
                                      "Excel\". Then click \"Import export files…\" above.")
            self.empty.place(relx=0.5, rely=0.62, anchor="center")
            return
        self.empty.place_forget()
        _, (start, end), _ = self._period()
        self.result = efatura.compare(self.project, start, end)
        n_ef = len(efatura.rows(self.project, start, end))
        self.lbl_count.configure(text=f"{n_ef} invoices in e-Fatura for this period")
        for key, (_, num) in self.tiles.items():
            num.configure(text=str(len(self.result[key])))
        self._show(self.group)

    def _show(self, key):
        self.group = key
        for k, (tile, _) in self.tiles.items():
            tile.configure(border_color=t.EVERGREEN if k == key else t.FROST, border_width=2 if k == key else 1)
        self.lbl_group.configure(text=next(g[2] for g in GROUPS if g[0] == key))
        self.tree.delete(*self.tree.get_children())
        if not self.result:
            return
        for i, row in enumerate(self._rows(key)):
            self.tree.insert("", "end", values=row, tags=("odd",) if i % 2 else ())

    def _rows(self, key):
        out = []
        for item in self.result[key]:
            if key == "missing":
                r = item
                out.append((r["date"], r["supplier_name"], r["supplier_nif"], r["number"], f"{r['total']:.2f}",
                            r.get("status") or ""))
            elif key == "not_in_ef":
                v = item["values"]
                out.append((str(v.get("date") or "")[:10], v.get("supplier") or "", v.get("_nif") or v.get("supplier_nif") or "",
                            v.get("invoice_number") or "", _money(v.get("total_value")), item["file_name"]))
            else:
                inv, r, extra = item
                v = inv["values"]
                note = "; ".join(extra) if key == "differ" else ("probable (same supplier, date and total)"
                                                                 if extra == "probable" else "")
                out.append((r["date"], r["supplier_name"] or v.get("supplier") or "", r["supplier_nif"], r["number"],
                            f"{r['total']:.2f}", note))
        return out

    # --- actions ---
    def _import(self):
        if import_exports(self.winfo_toplevel(), self.project):
            self.periods = [p for p in periods.options(history.years(self.project)) if p[0] != periods.CUSTOM]
            self.m_period.configure(values=[p[0] for p in self.periods])
            self._load()

    def _export(self):
        if not self.result:
            return
        short = self._period()[2]
        name = f"e-Fatura {os.path.basename(self.project)}" + (f" – {short}" if short else "")
        path = filedialog.asksaveasfilename(title="Save comparison", defaultextension=".xlsx",
                                            initialdir=self.project, initialfile=f"{name}.xlsx",
                                            filetypes=[("Excel", "*.xlsx")])
        if not path:
            return
        wb = Workbook()
        wb.remove(wb.active)
        for key, title, _, _ in GROUPS:
            ws = wb.create_sheet(title[:31])
            ws.append(["Date", "Supplier", "NIF", "Document", "Total", "Note"])
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill(start_color="204E27", end_color="204E27", fill_type="solid")
            for row in self._rows(key):
                ws.append(list(row))
            for col, w in zip("ABCDEF", (12, 34, 12, 34, 10, 40)):
                ws.column_dimensions[col].width = w
        wb.save(path)
        messagebox.showinfo("e-Fatura", "Comparison saved.")


def _money(v):
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return ""
