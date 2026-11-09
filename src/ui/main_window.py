"""App window: switches between the Welcome, Setup, Review, Settings and Done screens."""
import os
import sys
import threading

import customtkinter as ctk
from PIL import Image, ImageTk

from src.config import APP_CONFIG
from src.services import api_key as key_store
from src.services import settings, updater
from src.services.currency_converter import CurrencyConverter
from src.ui import background, theme as t
from src.ui.dialogs import UpdateDialog
from src.ui.screens.done import DoneScreen
from src.ui.screens.review import ReviewScreen
from src.ui.screens.settings_screen import SettingsScreen
from src.ui.screens.setup import SetupScreen
from src.ui.screens.welcome import WelcomeScreen
from src.utils import get_resource_path


class MainWindow(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("light")
        super().__init__(fg_color=t.SNOW)
        self.title(APP_CONFIG["NAME"])
        self.geometry("1120x760")
        self.minsize(980, 680)
        self._set_icon()
        t.resolve_fonts(self)

        self.screen = None
        self.update_info = None
        self.eur_rate = 0.92
        threading.Thread(target=self._fetch_rate, daemon=True).start()

        if key_store.get_api_key():
            self.show_setup()
        else:
            self._show(WelcomeScreen(self, on_done=self.show_setup))

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
    def _show(self, screen):
        if self.screen is not None:
            self.screen.destroy()
        self.screen = screen
        screen.pack(fill="both", expand=True)

    def show_setup(self):
        screen = SetupScreen(self, on_start=self.show_review, on_settings=self.show_settings,
                             eur_rate=self.eur_rate)
        self._show(screen)
        if self.update_info:
            screen.show_update(self.update_info, self._open_update)

    def show_settings(self):
        self._show(SettingsScreen(self, on_back=self.show_setup, on_update_found=self._update_found,
                                  eur_rate=self.eur_rate))

    def show_review(self, source, dest, delete_original, fields):
        key = key_store.get_api_key()
        if not key:
            self._show(WelcomeScreen(self, on_done=self.show_setup))
            return
        self._show(ReviewScreen(self, api_key=key, source_folder=source, dest_folder=dest,
                                delete_original=delete_original, filename_fields=fields,
                                on_back=self.show_setup, on_done=self.show_done))

    def show_done(self, renamed, skipped, failed, corrected, cost_usd, invoices, dest_folder, export):
        settings.add_usage(invoices, cost_usd)
        self._show(DoneScreen(self, renamed=renamed, skipped=skipped, corrected=corrected, failed=failed,
                              cost_eur=cost_usd * self.eur_rate, dest_folder=dest_folder,
                              on_export=export, on_restart=self.show_setup))

    # --- updates ---
    def _update_found(self, info, show_dialog=False):
        self.update_info = info
        if isinstance(self.screen, SetupScreen):
            self.screen.show_update(info, self._open_update)
        if show_dialog:
            self._open_update()

    def _open_update(self):
        if self.update_info:
            UpdateDialog(self, self.update_info, on_quit=self.destroy)
