"""Home: the folders (projects) this computer works with."""
import datetime
import os
from tkinter import filedialog

import customtkinter as ctk

from src.services import history
from src.ui import background, icons, theme as t


def nice_path(path, parts=3):
    bits = [b for b in path.replace("\\", "/").split("/") if b]
    return " › ".join(bits[-parts:]) if bits else path


def nice_date(iso):
    if not iso:
        return ""
    try:
        d = datetime.datetime.fromisoformat(iso)
    except ValueError:
        return iso[:10]
    return f"{d.day} {d.strftime('%b')}" + ("" if d.year == datetime.date.today().year else f" {d.year}")


class FolderRow(ctk.CTkFrame):
    def __init__(self, master, project, on_open, first):
        super().__init__(master, fg_color="transparent", corner_radius=0, cursor=t.HAND)
        p = project
        inner = ctk.CTkFrame(self, fg_color="transparent", cursor=t.HAND)
        inner.pack(fill="x", padx=24, pady=18)
        icon = ctk.CTkLabel(inner, text="", image=icons.tile("folder", first), cursor=t.HAND)
        icon.pack(side="left", padx=(0, 18))

        name = ctk.CTkFrame(inner, fg_color="transparent", width=330, height=44, cursor=t.HAND)
        name.pack(side="left")
        name.pack_propagate(False)
        exists = os.path.isdir(p["path"])
        t.label(name, os.path.basename(p["path"]) or p["path"], size=16, weight="bold").pack(anchor="w")
        t.label(name, nice_path(os.path.dirname(p["path"])) if exists else "Folder not found (moved or deleted?)",
                size=13, color=t.LICHEN if exists else t.AMBER).pack(anchor="w")

        def stat(value, caption, width):
            box = ctk.CTkFrame(inner, fg_color="transparent", width=width, height=44, cursor=t.HAND)
            box.pack(side="left")
            box.pack_propagate(False)
            t.label(box, value, size=16 if width < 200 else 14,
                    weight="bold" if width < 200 else "normal").pack(anchor="w")
            t.label(box, caption, size=12, color=t.LICHEN).pack(anchor="w")
            return box

        stat(str(p["invoices"]), "invoices", 110)
        stat(f"{p['total']:,.2f}", "total", 140)
        stat(f"Last run {nice_date(p['last_run'])}" if p["last_run"] else "No runs yet",
             f"{p['runs']} run{'s' if p['runs'] != 1 else ''}", 200)

        self.badge = ctk.CTkLabel(inner, text="", corner_radius=999, height=26, font=t.font(12, "bold"))
        self.badge.pack(side="right")
        if p["to_check"]:
            self._badge(f"  {p['to_check']} to check  ", t.AMBER_BG, t.AMBER)
        for w in [self, inner, icon, name, self.badge] + list(name.winfo_children()) + list(inner.winfo_children()):
            w.bind("<Button-1>", lambda _e: on_open(p["path"]), add="+")
            for c in w.winfo_children():
                c.bind("<Button-1>", lambda _e: on_open(p["path"]), add="+")
        self.bind("<Enter>", lambda _e: self.configure(fg_color=t.SNOWFIELD))
        self.bind("<Leave>", lambda _e: self.configure(fg_color="transparent"))

    def _badge(self, text, bg, fg):
        self.badge.configure(text=text, fg_color=bg, text_color=fg)

    def set_new(self, n, to_check):
        if n:
            self._badge(f"  {n} new file{'s' if n != 1 else ''}  ", t.SELECTED, t.EVERGREEN)
        elif not to_check:
            self._badge("  All done  ", "transparent", t.NEEDLE)


class HomeScreen(ctk.CTkFrame):
    def __init__(self, master, on_open_folder, on_all_invoices, on_settings):
        super().__init__(master, fg_color=t.SNOW, corner_radius=0)
        self.on_open_folder = on_open_folder

        bar = ctk.CTkFrame(self, fg_color=t.SNOW, corner_radius=0, height=66)
        bar.pack(fill="x")
        ctk.CTkLabel(bar, text="", image=icons.logo(26)).pack(side="left", padx=(32, 12), pady=18)
        t.label(bar, "Invoice Renamer", size=15, weight="bold").pack(side="left")
        ctk.CTkButton(bar, text="Settings", image=icons.line_icon("gear", 16, stroke=1.8), compound="left",
                      command=on_settings, height=36, width=0, corner_radius=8, fg_color=t.SNOW,
                      hover_color=t.SNOWFIELD, border_width=1, border_color=t.FROST, text_color=t.INK,
                      font=t.font(13)).pack(side="right", padx=(8, 32))
        t.secondary_button(bar, "All invoices", command=on_all_invoices, height=36).pack(side="right")
        self.update_slot = ctk.CTkFrame(bar, fg_color="transparent", width=1, height=36)
        self.update_slot.pack(side="right")
        t.divider(self).pack(fill="x")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=64, pady=(40, 32))
        head = ctk.CTkFrame(body, fg_color="transparent")
        head.pack(fill="x")
        left = ctk.CTkFrame(head, fg_color="transparent")
        left.pack(side="left")
        ctk.CTkLabel(left, text="Your folders", font=t.display(30), text_color=t.INK, anchor="w").pack(anchor="w")
        t.label(left, "Each folder keeps its invoices, runs and Excel together.", size=15,
                color=t.LICHEN).pack(anchor="w", pady=(6, 0))
        t.primary_button(head, "+ Add a folder", command=self._add, width=160, height=46).pack(side="right", anchor="s")

        self.projects = history.projects()
        if not self.projects:
            empty = ctk.CTkFrame(body, fg_color=t.SNOWFIELD, corner_radius=12)
            empty.pack(fill="x", pady=(28, 0))
            t.label(empty, "No folders yet", size=16, weight="bold").pack(anchor="w", padx=24, pady=(22, 4))
            t.label(empty, "Add the folder where you keep invoices (PDFs or photos). The app reads them, you check the values, "
                           "and everything is renamed and kept here for the Excel later.",
                    size=14, color=t.LICHEN, wraplength=760).pack(anchor="w", padx=24, pady=(0, 22))
            return

        box = ctk.CTkScrollableFrame(body, fg_color=t.SNOW, corner_radius=12, border_width=1,
                                     border_color=t.FROST, scrollbar_button_color=t.FROST,
                                     scrollbar_button_hover_color=t.FIELD_BORDER)
        box.pack(fill="both", expand=True, pady=(28, 0))
        self.rows = []
        for i, p in enumerate(self.projects):
            if i:
                t.divider(box).pack(fill="x")
            row = FolderRow(box, p, self.on_open_folder, first=i == 0)
            row.pack(fill="x")
            self.rows.append(row)
        # Count new PDFs per folder in the background (needs reading the files)
        background.run(self, lambda: [len(history.new_pdfs(p["path"])) if os.path.isdir(p["path"]) else 0
                                      for p in self.projects], self._new_counted)

    def _new_counted(self, counts):
        if isinstance(counts, Exception):
            return
        for row, p, n in zip(self.rows, self.projects, counts):
            row.set_new(n, p["to_check"])

    def show_update(self, info, on_click):
        for w in self.update_slot.winfo_children():
            w.destroy()
        ctk.CTkButton(self.update_slot, text=f"Update to {info.version}", command=on_click, height=36,
                      width=0, corner_radius=8, fg_color=t.SELECTED, hover_color=t.FROST,
                      text_color=t.EVERGREEN, font=t.font(13, "bold")).pack(side="right", padx=(0, 8))

    def _add(self):
        folder = filedialog.askdirectory(title="Choose a folder with invoices")
        if folder:
            history.add_project(folder)
            self.on_open_folder(os.path.abspath(folder))
