"""Small modal dialogs: API key entry and update prompt."""
import threading
import webbrowser

import customtkinter as ctk

from src.config import COLORS
from src.services import api_key as key_store
from src.services import updater
from src.services.gemini_service import validate_api_key

AISTUDIO_URL = "https://aistudio.google.com/apikey"


def _center(win, parent, w, h):
    parent.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - h) // 3
    win.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")


class ApiKeyDialog(ctk.CTkToplevel):
    """Asks for the Gemini API key, checks it works, and stores it in the OS keychain."""

    def __init__(self, master, on_saved=None, first_run=False):
        super().__init__(master)
        self.on_saved = on_saved
        self.title("Gemini API key")
        self.resizable(False, False)
        _center(self, master, 520, 300)
        self.transient(master)

        pad = {"padx": 24}
        ctk.CTkLabel(self, text="Welcome! One-time setup" if first_run else "Gemini API key",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", pady=(22, 6), **pad)
        ctk.CTkLabel(
            self, justify="left", wraplength=470, text_color=("gray30", "gray70"),
            text="The app uses Google Gemini to read invoices. Paste your API key below. "
                 "It is stored securely on this computer and never shared.",
        ).pack(anchor="w", **pad)
        link = ctk.CTkLabel(self, text="Get a key at aistudio.google.com/apikey",
                            text_color=COLORS["LIGHT_GREEN"], cursor="hand2")
        link.pack(anchor="w", pady=(4, 12), **pad)
        link.bind("<Button-1>", lambda e: webbrowser.open(AISTUDIO_URL))

        self.entry = ctk.CTkEntry(self, show="•", placeholder_text="AIza…", width=470)
        self.entry.pack(**pad)
        existing = key_store.get_api_key()
        if existing:
            self.entry.insert(0, existing)

        self.lbl_status = ctk.CTkLabel(self, text="", wraplength=470, justify="left")
        self.lbl_status.pack(anchor="w", pady=(6, 0), **pad)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", side="bottom", pady=18, **pad)
        self.btn_save = ctk.CTkButton(btns, text="Save", width=120, command=self._save,
                                      fg_color=COLORS["LIGHT_GREEN"], hover_color=COLORS["DARK_GREEN"])
        self.btn_save.pack(side="right")
        ctk.CTkButton(btns, text="Cancel", width=100, command=self.destroy, fg_color="transparent",
                      border_width=2, text_color=("gray10", "gray90")).pack(side="right", padx=10)

        self.entry.bind("<Return>", lambda e: self._save())
        self.after(100, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.entry.focus_set()
        except Exception:
            pass

    def _save(self):
        key = self.entry.get().strip()
        if not key:
            self.lbl_status.configure(text="Please paste a key.", text_color="red")
            return
        self.btn_save.configure(state="disabled", text="Checking…")
        self.lbl_status.configure(text="")

        def work():
            err = validate_api_key(key)
            self.after(0, lambda: self._done(key, err))

        threading.Thread(target=work, daemon=True).start()

    def _done(self, key, err):
        if err:
            self.btn_save.configure(state="normal", text="Save")
            self.lbl_status.configure(text=f"That key didn't work: {err}", text_color="red")
            return
        try:
            key_store.save_api_key(key)
        except Exception as e:
            self.btn_save.configure(state="normal", text="Save")
            self.lbl_status.configure(text=f"Couldn't save the key: {e}", text_color="red")
            return
        if self.on_saved:
            self.on_saved()
        self.destroy()


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

        ctk.CTkLabel(self, text=f"Version {info.version} is available",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w", padx=24, pady=(22, 8))
        notes = ctk.CTkTextbox(self, height=120, wrap="word")
        notes.insert("1.0", info.notes or "Improvements and fixes.")
        notes.configure(state="disabled")
        notes.pack(fill="x", padx=24)

        self.progress = ctk.CTkProgressBar(self, progress_color=COLORS["LIGHT_GREEN"])
        self.progress.set(0)
        self.lbl_status = ctk.CTkLabel(self, text="", text_color="gray")

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", side="bottom", padx=24, pady=18)
        self.btn_update = ctk.CTkButton(btns, text="Update now", width=140, command=self._update,
                                        fg_color=COLORS["LIGHT_GREEN"], hover_color=COLORS["DARK_GREEN"])
        self.btn_update.pack(side="right")
        self.btn_later = ctk.CTkButton(btns, text="Later", width=100, command=self.destroy,
                                       fg_color="transparent", border_width=2,
                                       text_color=("gray10", "gray90"))
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

        def work():
            try:
                path = updater.download(self.info, progress=lambda f: self.after(0, self.progress.set, f))
                self.after(0, lambda: self._install(path))
            except Exception as e:
                self.after(0, lambda: self._failed(e))

        threading.Thread(target=work, daemon=True).start()

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
        self.lbl_status.configure(text=f"Download failed: {e}", text_color="red")
