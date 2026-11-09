"""Update prompt dialog."""
import webbrowser

import customtkinter as ctk

from src.services import updater
from src.ui import background, theme as t


def _center(win, parent, w, h):
    parent.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - h) // 3
    win.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")


class UpdateDialog(ctk.CTkToplevel):
    """Offers to download and install a newer version."""

    def __init__(self, master, info, on_quit):
        super().__init__(master)
        self.info = info
        self.on_quit = on_quit
        self.title("Update available")
        self.resizable(False, False)
        _center(self, master, 480, 300)
        self.transient(master)

        self.configure(fg_color=t.SNOW)
        ctk.CTkLabel(self, text=f"Version {info.version} is ready", font=t.font(18, "bold"),
                     text_color=t.INK).pack(anchor="w", padx=24, pady=(22, 8))
        notes = ctk.CTkTextbox(self, height=120, wrap="word", fg_color=t.SNOWFIELD, text_color=t.INK,
                               font=t.font(13), corner_radius=8)
        notes.insert("1.0", info.notes or "Improvements and fixes.")
        notes.configure(state="disabled")
        notes.pack(fill="x", padx=24)

        self.progress = ctk.CTkProgressBar(self, progress_color=t.NEEDLE, fg_color=t.FROST, height=4)
        self.progress.set(0)
        self.lbl_status = ctk.CTkLabel(self, text="", text_color=t.LICHEN, font=t.font(13), wraplength=430,
                                       justify="left")

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", side="bottom", padx=24, pady=18)
        self.btn_update = t.primary_button(btns, "Update now", command=self._update, width=140, height=40)
        self.btn_update.pack(side="right")
        self.btn_later = t.secondary_button(btns, "Later", command=self.destroy, width=90, height=40)
        self.btn_later.pack(side="right", padx=10)

    def _update(self):
        if not self.info.asset_url:
            webbrowser.open(self.info.page_url)
            self.destroy()
            return
        self.btn_update.configure(state="disabled", text="Downloading…")
        self.btn_later.configure(state="disabled")
        self.progress.pack(fill="x", padx=24, pady=(12, 0))
        self.lbl_status.pack(anchor="w", padx=24)

        box = background.Mailbox(self)
        background.run(self, lambda: updater.download(self.info, progress=lambda f: box.post(lambda: self.progress.set(f))),
                       lambda r: self._failed(r) if isinstance(r, Exception) else self._install(r))

    def _install(self, path):
        updater.launch_installer(path)
        if updater.sys.platform == "win32":
            self.lbl_status.configure(text="Installing… the app will reopen by itself.")
            self.after(800, self.on_quit)
        else:
            self.lbl_status.configure(
                text="Drag the new app into Applications (replace the old one), then reopen it.")
            self.btn_later.configure(state="normal", text="Close")

    def _failed(self, e):
        self.btn_update.configure(state="normal", text="Try again")
        self.btn_later.configure(state="normal")
        self.lbl_status.configure(text=f"Download failed: {e}", text_color=t.RED)
