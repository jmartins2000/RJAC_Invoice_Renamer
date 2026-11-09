"""Invoice table (ttk.Treeview) styled to match the app; used by Folder and All invoices."""
import os
import subprocess
import sys
from tkinter import messagebox, ttk

import customtkinter as ctk

from src.services import fields as fieldmod
from src.ui import theme as t

STATUS = {"read": "To check", "confirmed": "Checked", "renamed": "Renamed"}


def style(widget):
    s = ttk.Style(widget)
    s.theme_use("default")
    bg, fg, head, sel, line = (t.c(x) for x in (t.SNOW, t.INK, t.SNOWFIELD, t.SELECTED, t.LICHEN))
    s.configure("Inv.Treeview", background=bg, fieldbackground=bg, foreground=fg, rowheight=30, borderwidth=0,
                font=(t.SANS, 12))
    s.configure("Inv.Treeview.Heading", background=head, foreground=line, relief="flat",
                font=(t.SANS, 11, "bold"), padding=(8, 6))
    s.map("Inv.Treeview", background=[("selected", sel)], foreground=[("selected", fg)])
    s.map("Inv.Treeview.Heading", background=[("active", t.c(t.FROST))])


def open_file(path):
    if not os.path.exists(path):
        messagebox.showinfo("File not found", f"This file is no longer at:\n{path}")
        return
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class InvoiceTable(ctk.CTkFrame):
    """rows: history rows (values, status, file_name, folder, project)."""

    def __init__(self, master, field_defs, extra=("_file", "_status")):
        super().__init__(master, fg_color=t.SNOW, corner_radius=10, border_width=1, border_color=t.FROST)
        style(self)
        self.fields = field_defs
        self.columns = [f.key for f in field_defs] + list(extra)
        titles = {"_file": "File", "_folder": "Folder", "_status": "Status"}
        self.tree = ttk.Treeview(self, columns=self.columns, show="headings", style="Inv.Treeview")
        for f in field_defs:
            self.tree.heading(f.key, text=f.label, command=lambda k=f.key: self.sort(k))
            self.tree.column(f.key, width=100 if f.type in ("date", "number") else 160,
                             anchor="e" if f.type == "number" else "w", stretch=f.type == "text")
        for c in extra:
            self.tree.heading(c, text=titles[c], command=lambda k=c: self.sort(k))
            self.tree.column(c, width={"_file": 220, "_folder": 150, "_status": 90}[c], anchor="w",
                             stretch=c == "_file")
        sb = ctk.CTkScrollbar(self, command=self.tree.yview, button_color=t.FROST, button_hover_color=t.FIELD_BORDER)
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 4), pady=6)
        self.tree.pack(fill="both", expand=True, padx=(6, 0), pady=6)
        self.tree.tag_configure("odd", background=t.c(t.ROW_ALT))
        self.tree.tag_configure("check", foreground=t.c(t.AMBER))
        self.tree.bind("<Double-1>", self._open)
        self.rows, self._sort = [], (None, False)

    def cell(self, row, key):
        if key == "_file":
            return row["file_name"]
        if key == "_folder":
            return os.path.basename(row.get("project") or row["folder"] or "")
        if key == "_status":
            return STATUS.get(row["status"], row["status"])
        f = next(x for x in self.fields if x.key == key)
        return fieldmod.display_value(f, row["values"].get(key))

    def set_rows(self, rows):
        self.rows = rows
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(rows):
            tags = (["odd"] if i % 2 else []) + (["check"] if r["status"] == "read" else [])
            self.tree.insert("", "end", iid=str(i), values=[self.cell(r, c) for c in self.columns], tags=tags)

    def sort(self, key):
        same = self._sort[0] == key
        rev = not self._sort[1] if same else False
        self._sort = (key, rev)

        def k(r):
            v = r["values"].get(key) if not key.startswith("_") else self.cell(r, key)
            return (v is None or v == "", v if isinstance(v, (int, float)) else str(v or "").lower())
        self.set_rows(sorted(self.rows, key=k, reverse=rev))

    def _open(self, _e):
        sel = self.tree.selection()
        if sel:
            r = self.rows[int(sel[0])]
            open_file(os.path.join(r["folder"], r["file_name"]))
