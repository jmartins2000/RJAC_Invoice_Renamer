"""Shown after renaming."""
import os
import subprocess
import sys

import customtkinter as ctk

from src.ui.feedback_dialog import feedback_button
from src.ui import icons, theme as t


def open_folder(path):
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class DoneScreen(ctk.CTkFrame):
    def __init__(self, master, renamed, skipped, corrected, failed, cost_eur, dest_folder,
                 on_export, on_back, folder_name=""):
        super().__init__(master, fg_color=t.SNOW, corner_radius=0)
        bar = ctk.CTkFrame(self, fg_color=t.SNOW, corner_radius=0, height=62)
        bar.pack(fill="x")
        ctk.CTkButton(bar, text=f"  Back to {folder_name}" if folder_name else "  Back",
                      image=icons.line_icon("arrow_left"), compound="left", height=34, width=0, corner_radius=8,
                      fg_color=t.SNOW, hover_color=t.SNOWFIELD, border_width=1, border_color=t.FROST,
                      text_color=t.INK, font=t.font(13), command=on_back).pack(side="left", padx=24, pady=14)
        feedback_button(bar).pack(side="right", padx=24)
        col = ctk.CTkFrame(self, fg_color="transparent")
        col.place(relx=0.5, rely=0.47, anchor="center")

        ctk.CTkLabel(col, text="", image=icons.big_check(56)).pack(anchor="w", pady=(0, 28))
        noun = "invoice" if renamed == 1 else "invoices"
        ctk.CTkLabel(col, text=f"{renamed} {noun} renamed", font=t.display(44), text_color=t.INK,
                     anchor="w").pack(anchor="w")
        detail = f"Saved in {os.path.basename(dest_folder) or dest_folder}."
        if skipped:
            detail += f" {skipped} file{'s were' if skipped > 1 else ' was'} skipped and left untouched."
        if failed:
            detail += f" {failed} could not be copied (see the message shown before)."
        t.label(col, detail, size=15, color=t.LICHEN, wraplength=520).pack(anchor="w", pady=(10, 28))

        btns = ctk.CTkFrame(col, fg_color="transparent")
        btns.pack(anchor="w")
        t.primary_button(btns, "Open folder", command=lambda: open_folder(dest_folder), width=140).pack(side="left")
        self.btn_export = t.secondary_button(btns, "Export to Excel", height=44, size=14,
                                             command=lambda: on_export(self.btn_export), width=150)
        self.btn_export.pack(side="left", padx=10)

        t.divider(col).pack(fill="x", pady=(28, 22))
        stats = ctk.CTkFrame(col, fg_color="transparent")
        stats.pack(anchor="w")
        for value, name in ((renamed, "renamed"), (corrected, "corrected by you"), (skipped, "skipped"),
                            (f"€{cost_eur:.2f}", "Gemini cost")):
            box = ctk.CTkFrame(stats, fg_color="transparent")
            box.pack(side="left", padx=(0, 32))
            t.label(box, str(value), size=20, weight="bold").pack(anchor="w")
            t.label(box, name, size=12, color=t.LICHEN).pack(anchor="w")
