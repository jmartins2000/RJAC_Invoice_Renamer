import customtkinter as ctk
from tkinter import filedialog, messagebox
import tkinter as tk
from PIL import Image, ImageTk
import os
import sys
import threading

from src.config import COLORS, APP_CONFIG
from src.utils import get_resource_path
from src.ui.review_view import ReviewView
from src.ui.dialogs import ApiKeyDialog, UpdateDialog
from src.services import api_key as key_store
from src.services import updater
from src.version import __version__

class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Window Setup
        self.title(APP_CONFIG["NAME"])
        self.geometry(APP_CONFIG["SIZE"])
        
        # Set appearance
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("green")

        # Window Icon
        # On Windows, .ico files are preferred for the title bar to avoid color channel swaps
        try:
            # Try to load .ico first
            icon_path_ico = get_resource_path("assets/RJAC-logo.ico")
            if os.path.exists(icon_path_ico):
                 self.iconbitmap(icon_path_ico)
            else:
                # Fallback to PNG if ICO missing
                icon_path_png = get_resource_path(APP_CONFIG["ICON"])
                icon_img = Image.open(icon_path_png)
                self.iconphoto(False, ImageTk.PhotoImage(icon_img))
        except Exception as e:
             print(f"Could not set window icon: {e}")

        # Layout Configuration
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- Main Container ---
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.grid(row=0, column=0, sticky="nsew", padx=40, pady=40)
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(1, weight=1) # Allow content to expand

        # State
        self.source_path = None
        self.dest_path = None

        # --- 1. Header Section (Always visible) ---
        self.build_header()
        
        # --- 2. Content Area (Swappable) ---
        self.content_area = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.content_area.grid(row=1, column=0, sticky="nsew")
        self.content_area.grid_columnconfigure(0, weight=1)
        self.content_area.grid_rowconfigure(0, weight=1)

        # Initialize Home View
        self.show_home_view()

        # --- 3. Footer/Status ---
        self.build_footer()

        self.after(400, self._startup_checks)

    # --- Startup: API key + updates ---
    def _startup_checks(self):
        if not key_store.get_api_key():
            ApiKeyDialog(self, first_run=True)
        if getattr(sys, "frozen", False) or os.environ.get("RJAC_CHECK_UPDATES"):
            threading.Thread(target=self._check_updates, daemon=True).start()

    def _check_updates(self):
        info = updater.check_for_update()
        if info:
            self.after(0, lambda: UpdateDialog(self, info, on_quit=self.destroy))

    def open_settings(self):
        ApiKeyDialog(self)

    def build_header(self):
        """Logo and Title"""
        header_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        header_frame.grid_columnconfigure(0, weight=1)

        # Simplified Header for Compactness
        # Logo
        logo_path = get_resource_path(APP_CONFIG["ICON"])
        try:
            pil_image = Image.open(logo_path)
            self.logo_image = ctk.CTkImage(light_image=pil_image, 
                                         dark_image=pil_image, 
                                         size=(60, 60)) # Smaller logo for header
            
            logo_label = ctk.CTkLabel(header_frame, image=self.logo_image, text="")
            logo_label.pack(side="left", padx=(0, 15))
        except Exception:
            pass

        # Title
        title_label = ctk.CTkLabel(header_frame, 
                                 text=APP_CONFIG["NAME"], 
                                 font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"),
                                 text_color=COLORS["WHITE"])
        title_label.pack(side="left", anchor="center")

    def _validate_field_selection(self):
        """Ensure at least one field is selected"""
        if not any([
            self.field_date_var.get(),
            self.field_value_var.get(),
            self.field_invoice_num_var.get(),
            self.field_supplier_var.get(),
            self.field_original_var.get()
        ]):
            # Re-enable the checkbox that was just unchecked
            # Find which one was unchecked and re-enable it
            messagebox.showwarning("Invalid Selection", "At least one field must be selected for the filename.")
            # Force re-check by setting all back if none selected
            self.field_date_var.set(True)
    
    def show_home_view(self):
        # Clear content area
        for widget in self.content_area.winfo_children():
            widget.destroy()
            
        self.review_view = None # Cleanup

        # Rebuild Home Card
        self.build_action_card()

    def show_review_view(self):
        if not self.source_path:
            # Show error if no source folder
            messagebox.showwarning("Missing Folder", "Please select a Source Directory containing your invoices first.")
            return

        api_key = key_store.get_api_key()
        if not api_key:
            ApiKeyDialog(self, first_run=True)
            return

        # Ensure content_area is clear
        for widget in self.content_area.winfo_children():
            widget.destroy()

        # Gather field selections
        filename_fields = {
            'date': self.field_date_var.get(),
            'value': self.field_value_var.get(),
            'invoice_number': self.field_invoice_num_var.get(),
            'supplier': self.field_supplier_var.get(),
            'original': self.field_original_var.get()
        }

        self.review_view = ReviewView(
            self.content_area,
            api_key=api_key,
            source_folder=self.source_path,
            dest_folder=self.dest_path,
            delete_original=self.delete_original_var.get(),
            filename_fields=filename_fields,
            on_back_home=self.show_home_view
        )
        self.review_view.pack(fill="both", expand=True)

    def build_action_card(self):
        """Main input area styled as a card"""
        self.card_frame = ctk.CTkFrame(self.content_area, corner_radius=15, fg_color=("white", "#2b2b2b"))
        self.card_frame.pack(fill="both", expand=True, pady=10)
        self.card_frame.grid_columnconfigure(0, weight=1)
        
        # Centering wrapper
        center_wrapper = ctk.CTkFrame(self.card_frame, fg_color="transparent")
        center_wrapper.pack(expand=True, fill="x", padx=20)
        center_wrapper.grid_columnconfigure(0, weight=1)

        # --- Step 1: Source ---
        self.create_step_widget(
            parent=center_wrapper,
            row=0,
            title="1. Source Directory",
            desc="Choose the folder containing your original invoice files.",
            btn_text="Browse Folder",
            btn_command=self.select_source_folder,
            path_variable_name="lbl_source_path",
            is_dest=False
        )

        # Divider
        separator = ctk.CTkFrame(center_wrapper, height=2, fg_color=("#f0f0f0", "#3a3a3a"))
        separator.grid(row=1, column=0, sticky="ew", padx=30, pady=10)

        # --- Step 2: Destination ---
        self.create_step_widget(
            parent=center_wrapper,
            row=2,
            title="2. Destination Directory",
            desc="Choose where the renamed files will be saved.",
            btn_text="Set Destination",
            btn_command=self.select_dest_folder,
            path_variable_name="lbl_dest_path",
            is_dest=True
        )

        # Divider
        separator2 = ctk.CTkFrame(center_wrapper, height=2, fg_color=("#f0f0f0", "#3a3a3a"))
        separator2.grid(row=3, column=0, sticky="ew", padx=30, pady=10)

        # --- Step 3: Options ---
        options_frame = ctk.CTkFrame(center_wrapper, fg_color="transparent")
        options_frame.grid(row=4, column=0, sticky="ew", padx=30, pady=20)
        
        self.delete_original_var = ctk.BooleanVar(value=True)
        
        self.chk_delete = ctk.CTkCheckBox(
            options_frame, 
            text="Delete original files after renaming",
            variable=self.delete_original_var,
            font=ctk.CTkFont(size=14),
            fg_color=COLORS["LIGHT_GREEN"],
            hover_color=COLORS["DARK_GREEN"],
            checkmark_color="white",
            border_color=COLORS["GRAY_SUBTEXT"],
            border_width=2
        )
        self.chk_delete.pack(anchor="w", pady=(0, 15))
        
        # --- Filename Fields Selection ---
        fields_label = ctk.CTkLabel(
            options_frame,
            text="Select fields to include in filename:",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=("black", "white")
        )
        fields_label.pack(anchor="w", pady=(0, 10))
        
        # Create checkboxes for each field
        self.field_date_var = ctk.BooleanVar(value=True)
        self.field_value_var = ctk.BooleanVar(value=True)
        self.field_invoice_num_var = ctk.BooleanVar(value=True)
        self.field_supplier_var = ctk.BooleanVar(value=True)
        self.field_original_var = ctk.BooleanVar(value=True)
        
        fields_checkboxes_frame = ctk.CTkFrame(options_frame, fg_color="transparent")
        fields_checkboxes_frame.pack(anchor="w")
        
        self.chk_date = ctk.CTkCheckBox(
            fields_checkboxes_frame,
            text="Date",
            variable=self.field_date_var,
            command=self._validate_field_selection,
            font=ctk.CTkFont(size=13),
            fg_color=COLORS["LIGHT_GREEN"],
            hover_color=COLORS["DARK_GREEN"],
            checkmark_color="white",
            border_color=COLORS["GRAY_SUBTEXT"],
            border_width=2
        )
        self.chk_date.pack(side="left", padx=(0, 15))
        
        self.chk_value = ctk.CTkCheckBox(
            fields_checkboxes_frame,
            text="Value",
            variable=self.field_value_var,
            command=self._validate_field_selection,
            font=ctk.CTkFont(size=13),
            fg_color=COLORS["LIGHT_GREEN"],
            hover_color=COLORS["DARK_GREEN"],
            checkmark_color="white",
            border_color=COLORS["GRAY_SUBTEXT"],
            border_width=2
        )
        self.chk_value.pack(side="left", padx=(0, 15))
        
        self.chk_invoice_num = ctk.CTkCheckBox(
            fields_checkboxes_frame,
            text="Invoice Number",
            variable=self.field_invoice_num_var,
            command=self._validate_field_selection,
            font=ctk.CTkFont(size=13),
            fg_color=COLORS["LIGHT_GREEN"],
            hover_color=COLORS["DARK_GREEN"],
            checkmark_color="white",
            border_color=COLORS["GRAY_SUBTEXT"],
            border_width=2
        )
        self.chk_invoice_num.pack(side="left", padx=(0, 15))
        
        self.chk_supplier = ctk.CTkCheckBox(
            fields_checkboxes_frame,
            text="Supplier",
            variable=self.field_supplier_var,
            command=self._validate_field_selection,
            font=ctk.CTkFont(size=13),
            fg_color=COLORS["LIGHT_GREEN"],
            hover_color=COLORS["DARK_GREEN"],
            checkmark_color="white",
            border_color=COLORS["GRAY_SUBTEXT"],
            border_width=2
        )
        self.chk_supplier.pack(side="left", padx=(0, 15))
        
        self.chk_original = ctk.CTkCheckBox(
            fields_checkboxes_frame,
            text="Original Filename",
            variable=self.field_original_var,
            command=self._validate_field_selection,
            font=ctk.CTkFont(size=13),
            fg_color=COLORS["LIGHT_GREEN"],
            hover_color=COLORS["DARK_GREEN"],
            checkmark_color="white",
            border_color=COLORS["GRAY_SUBTEXT"],
            border_width=2
        )
        self.chk_original.pack(side="left")

        # --- Start Button ---
        self.btn_start = ctk.CTkButton(
            center_wrapper,
            text="Start Processing",
            command=self.show_review_view,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=COLORS["LIGHT_GREEN"],
            hover_color=COLORS["DARK_GREEN"],
            height=50,
            corner_radius=10
        )
        self.btn_start.grid(row=5, column=0, pady=(30, 10))
        
        # Restore state if exists
        if self.source_path:
            self.lbl_source_path.configure(text=self.source_path, text_color=("black", "white"))
        if self.dest_path:
            self.lbl_dest_path.configure(text=self.dest_path, text_color=("black", "white"))

    def create_step_widget(self, parent, row, title, desc, btn_text, btn_command, path_variable_name, is_dest):
        """Helper to create consistent step rows"""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", padx=30, pady=20)
        frame.grid_columnconfigure(1, weight=1)

        # Info (Left side)
        info_frame = ctk.CTkFrame(frame, fg_color="transparent")
        info_frame.grid(row=0, column=0, sticky="w")
        
        lbl_title = ctk.CTkLabel(info_frame, text=title, 
                               font=ctk.CTkFont(size=16, weight="bold"),
                               text_color=("black", "white"))
        lbl_title.pack(anchor="w")
        
        lbl_desc = ctk.CTkLabel(info_frame, text=desc, 
                              font=ctk.CTkFont(size=12),
                              text_color=COLORS["GRAY_SUBTEXT"])
        lbl_desc.pack(anchor="w")

        # Button
        btn = ctk.CTkButton(
            frame, 
            text=btn_text, 
            command=btn_command,
            font=ctk.CTkFont(family="Segoe UI", weight="bold"),
            fg_color=COLORS["LIGHT_GREEN"],
            hover_color=COLORS["DARK_GREEN"],
            height=35,
            width=150,
            corner_radius=8
        )
        btn.grid(row=0, column=2, padx=(20, 0))

        # Path Display (Full width below)
        path_frame = ctk.CTkFrame(frame, fg_color=("#f8f9fa", "#333333"), corner_radius=6)
        path_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(15, 0))
        
        path_lbl = ctk.CTkLabel(
            path_frame, 
            text="No folder selected", 
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color="gray",
            anchor="w",
            padx=10,
            pady=8
        )
        path_lbl.pack(fill="x")
        
        setattr(self, path_variable_name, path_lbl)

    def build_footer(self):
        """Footer area"""
        footer_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        footer_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        
        lbl_version = ctk.CTkLabel(footer_frame, text=f"v{__version__}", text_color="gray", font=ctk.CTkFont(size=10))
        lbl_version.pack(side="right")

        btn_settings = ctk.CTkButton(
            footer_frame, text="API key…", command=self.open_settings, width=80, height=24,
            fg_color="transparent", border_width=1, text_color=("gray30", "gray70"),
            hover_color=("gray85", "gray25"), font=ctk.CTkFont(size=11))
        btn_settings.pack(side="left")

    def select_source_folder(self):
        folder_path = filedialog.askdirectory(title="Select Source Folder")
        if folder_path:
            self.source_path = folder_path
            self.lbl_source_path.configure(text=folder_path, text_color=("black", "white"))
            
            if not self.dest_path:
                self.dest_path = folder_path
                self.lbl_dest_path.configure(text=f"{folder_path} (Default)", text_color="gray")

    def select_dest_folder(self):
        folder_path = filedialog.askdirectory(title="Select Destination Folder")
        if folder_path:
            self.dest_path = folder_path
            self.lbl_dest_path.configure(text=folder_path, text_color=("black", "white"))
