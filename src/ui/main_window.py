"""App window: Welcome → Home (folders) → Folder → Review → Done, plus All invoices, Settings, Fields."""
import os
import sys
import threading

import customtkinter as ctk
from PIL import Image, ImageTk

from src.config import APP_CONFIG
from src.services import api_key as key_store
from src.services import history, models, settings, updater
from src.services.currency_converter import CurrencyConverter
from src.ui import background, theme as t
from src.ui.dialogs import UpdateDialog
from src.ui.screens.done import DoneScreen
from src.ui.screens.fields_screen import FieldsScreen
from src.ui.screens.folder import FolderScreen
from src.ui.screens.history_screen import HistoryScreen
from src.ui.screens.home import HomeScreen
from src.ui.screens.review import ReviewScreen
from src.ui.screens.settings_screen import SettingsScreen
from src.ui.screens.welcome import WelcomeScreen
from src.utils import get_resource_path

APPEARANCE = {"system": "system", "light": "light", "dark": "dark"}


class MainWindow(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode(APPEARANCE.get(settings.load().get("appearance"), "system"))
        super().__init__(fg_color=t.SNOW)
        self.title(APP_CONFIG["NAME"])
        # Fit small laptop screens (e.g. 1366x768 at 125% scaling ≈ 1093x614 usable)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(1120, sw - 40), min(760, sh - 90)
        self.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
        self.minsize(min(900, w), min(600, h))
        self._set_icon()
        t.resolve_fonts(self)
        from src.ui import scrolling
        scrolling.install(self)

        self.screen = None
        self.show_current = None  # re-creates the current screen (used after changing day/night)
        self.update_info = None
        self.eur_rate = 0.92
        threading.Thread(target=self._fetch_rate, daemon=True).start()
        models.warm()

        if key_store.get_api_key():
            self.show_home()
        else:
            self._show(WelcomeScreen(self, on_done=self.show_home), None)

        if getattr(sys, "frozen", False) or os.environ.get("RJAC_CHECK_UPDATES"):
            background.run(self, updater.check_for_update, lambda info: info and self._update_found(info))

    def _set_icon(self):
        try:
            ico = get_resource_path("assets/RJAC-logo.ico")
            if sys.platform == "win32" and os.path.exists(ico):
                self.iconbitmap(ico)
            else:
                self._icon_img = ImageTk.PhotoImage(Image.open(get_resource_path(APP_CONFIG["ICON"])))
                self.iconphoto(True, self._icon_img)
        except Exception as e:
            print(f"Could not set window icon: {e}")

    def _fetch_rate(self):
        self.eur_rate = CurrencyConverter.get_usd_to_eur_rate() or 0.92

    # --- screens ---
    def _show(self, screen, again):
        if self.screen is not None:
            self.screen.destroy()
        self.screen = screen
        self.show_current = again
        self.configure(fg_color=t.SNOW)
        screen.pack(fill="both", expand=True)

    def show_home(self):
        screen = HomeScreen(self, on_open_folder=self.show_folder, on_all_invoices=self.show_all,
                            on_settings=self.show_settings)
        self._show(screen, self.show_home)
        if self.update_info:
            screen.show_update(self.update_info, self._open_update)

    def show_folder(self, path):
        self._show(FolderScreen(self, path, on_back=self.show_home, on_review=self.show_review,
                                on_customize=lambda: self.show_fields(back=lambda: self.show_folder(path)),
                                eur_rate=self.eur_rate), lambda: self.show_folder(path))

    def show_review(self, path, _only_new=False):
        key = key_store.get_api_key()
        if not key:
            self._show(WelcomeScreen(self, on_done=lambda: self.show_folder(path)), None)
            return
        project = history.project(path) or {}
        dest = project.get("dest_folder") or path
        self._show(ReviewScreen(self, api_key=key, source_folder=path, dest_folder=dest,
                                on_back=lambda: self.show_folder(path),
                                on_done=lambda **kw: self.show_done(path, **kw)), lambda: self.show_review(path))

    def show_done(self, path, renamed, skipped, failed, corrected, cost_usd, invoices, dest_folder, export):
        settings.add_usage(invoices, cost_usd)
        self._show(DoneScreen(self, renamed=renamed, skipped=skipped, corrected=corrected, failed=failed,
                              cost_eur=cost_usd * self.eur_rate, dest_folder=dest_folder, on_export=export,
                              on_back=lambda: self.show_folder(path),
                              folder_name=os.path.basename(path)), None)

    def show_all(self):
        self._show(HistoryScreen(self, on_back=self.show_home, on_open_folder=self.show_folder), self.show_all)

    def show_settings(self):
        self._show(SettingsScreen(self, on_back=self.show_home, on_update_found=self._update_found,
                                  on_fields=lambda: self.show_fields(back=self.show_settings),
                                  on_appearance=self.set_appearance, eur_rate=self.eur_rate), self.show_settings)

    def show_fields(self, back=None):
        back = back or self.show_settings
        self._show(FieldsScreen(self, on_back=back), lambda: self.show_fields(back))

    def set_appearance(self, mode):
        settings.save(appearance=mode)
        ctk.set_appearance_mode(APPEARANCE.get(mode, "system"))
        if self.show_current:
            self.after(50, self.show_current)  # redraw canvases, tables and icons in the new colours

    # --- updates ---
    def _update_found(self, info, show_dialog=False):
        self.update_info = info
        if isinstance(self.screen, HomeScreen):
            self.screen.show_update(info, self._open_update)
        if show_dialog:
            self._open_update()

    def _open_update(self):
        if self.update_info:
            UpdateDialog(self, self.update_info, on_quit=self.destroy)
