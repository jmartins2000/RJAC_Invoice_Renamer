import customtkinter as ctk
from PIL import Image
from src.config import COLORS
from src.services.pdf_service import PDFService
from src.services.gemini_service import GeminiService
from src.services.file_manager import FileManager
from src.services.excel_exporter import ExcelExporter
from src.services.currency_converter import CurrencyConverter
from src.ui.pdf_preview import PDFPreviewFrame
from src.utils import get_resource_path
from tkinter import messagebox
import threading
import os
import queue
from concurrent.futures import ThreadPoolExecutor

# Parallel Gemini requests. Failed requests are retried with backoff inside GeminiService.
MAX_WORKERS = 6
POLL_MS = 100

class ReviewView(ctk.CTkFrame):
    def __init__(self, master, api_key, source_folder, dest_folder, delete_original, filename_fields, on_back_home):
        super().__init__(master, fg_color="transparent")
        self.source_folder = source_folder
        self.dest_folder = dest_folder
        self.delete_original = delete_original
        self.filename_fields = filename_fields  # Dict of which fields to include
        self.on_back_home = on_back_home
        
        # Services
        self.gemini = GeminiService(api_key)
        self.executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        # Worker threads never touch Tk directly; they post callables here and the UI thread runs them.
        self.ui_queue = queue.Queue()
        self._closed = False
        self.eur_rate = None
        threading.Thread(target=self._fetch_eur_rate, daemon=True).start()

        # State
        self.files = self._scan_pdf_files()
        self.current_index = 0
        self.data_cache = {}   # filepath -> confirmed/extracted field values
        self.errors = {}       # filepath -> error message (extraction failed)
        self.in_flight = set()
        
        # Animation State
        self.loading_frames = []
        self.loading_idx = 0
        self.animation_id = None
        self._load_assets()
        
        # Layout
        self.grid_columnconfigure(0, weight=1, uniform="columns") # Preview - 50%
        self.grid_columnconfigure(1, weight=1, uniform="columns") # Data - 50%
        self.grid_rowconfigure(0, weight=1)

        # --- Left: PDF Preview ---
        self.preview_container = ctk.CTkFrame(self, fg_color=("gray90", "gray20"))
        self.preview_container.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
        self.preview_container.grid_columnconfigure(0, weight=1)
        self.preview_container.grid_rowconfigure(0, weight=1)
        
        # Bind to preview container resize to update PDF scaling
        self.preview_container.bind("<Configure>", self._update_pdf_scaling)

        self.pdf_view = PDFPreviewFrame(self.preview_container, fg_color="transparent")
        self.pdf_view.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        # --- Right: Data & Controls ---
        self.data_container = ctk.CTkFrame(self, fg_color="transparent")
        self.data_container.grid(row=0, column=1, sticky="nsew")
        self.data_container.grid_columnconfigure(0, weight=1)
        
        # Bind resize event to update wraplengths
        self.data_container.bind("<Configure>", self._update_wraplengths)

        # Back Button (Top Left) - Styled like Previous
        self.btn_back = ctk.CTkButton(
            self.data_container,
            text="Back",
            command=self._go_home,
            fg_color="transparent",
            border_width=2,
            text_color=("gray10", "gray90"),
            hover_color=("gray80", "gray30"),
            width=80
        )
        self.btn_back.pack(pady=(20, 0), anchor="w", padx=0)

        # 1. Header
        self.lbl_filename = ctk.CTkLabel(
            self.data_container, 
            text="Loading...", 
            font=ctk.CTkFont(size=18, weight="bold"),
            wraplength=400
        )
        self.lbl_filename.pack(pady=(10, 5), anchor="w", fill="x", padx=10)
        
        self.lbl_progress = ctk.CTkLabel(self.data_container, text="Invoice 1 of X", text_color="gray")
        self.lbl_progress.pack(anchor="w", pady=(0, 20))
        
        # Pack bottom elements first (from bottom up) to give them priority
        # 5. Action Buttons (at very bottom, initially hidden)
        self.action_buttons_frame = ctk.CTkFrame(self.data_container, fg_color="transparent", height=50)
        self.action_buttons_frame.pack(fill="x", pady=(0, 20), side="bottom")
        self.action_buttons_frame.pack_propagate(False)  # Maintain height even when empty
        
        self.btn_download_excel = ctk.CTkButton(
            self.action_buttons_frame,
            text="Download Spreadsheet",
            command=self.download_spreadsheet,
            fg_color=COLORS["LIGHT_GREEN"],
            hover_color=COLORS["DARK_GREEN"],
            height=32,
            width=180,
            font=ctk.CTkFont(size=13)
        )
        # Don't pack yet
        
        self.btn_rename_all = ctk.CTkButton(
            self.action_buttons_frame,
            text="Rename All Files",
            command=self.rename_all_files,
            fg_color=COLORS["LIGHT_GREEN"],
            hover_color=COLORS["DARK_GREEN"],
            height=32,
            width=180,
            font=ctk.CTkFont(size=13)
        )
        # Don't pack yet
        
        # 4. Navigation Buttons (above action buttons)
        self.nav_frame = ctk.CTkFrame(self.data_container, fg_color="transparent")
        self.nav_frame.pack(fill="x", pady=(0, 10), side="bottom")

        self.btn_prev = ctk.CTkButton(
            self.nav_frame, 
            text="Previous", 
            command=self.prev_invoice,
            fg_color="transparent",
            border_width=2,
            text_color=("gray10", "gray90"),
            hover_color=("gray80", "gray30"),
            width=100
        )
        self.btn_prev.pack(side="left", padx=(0, 10))

        self.btn_next = ctk.CTkButton(
            self.nav_frame, 
            text="Confirm & Next", 
            command=self.next_invoice,
            fg_color=COLORS["LIGHT_GREEN"],
            hover_color=COLORS["DARK_GREEN"],
            width=160
        )
        self.btn_next.pack(side="right")
        
        # 3. Completion Counter (above navigation)
        self.status_frame = ctk.CTkFrame(self.data_container, fg_color="transparent")
        self.status_frame.pack(fill="x", pady=(5, 10), side="bottom")
        
        self.lbl_completion = ctk.CTkLabel(
            self.status_frame,
            text=f"Completed: 0/{len(self.files)}",
            text_color="gray",
            font=ctk.CTkFont(size=11)
        )
        self.lbl_completion.pack(side="left", anchor="w")

        # 2. Main Content Area (fills remaining space after bottom elements are positioned)
        self.content_frame_wrapper = ctk.CTkFrame(self.data_container, fg_color="transparent")
        self.content_frame_wrapper.pack(fill="both", expand=True, pady=(0, 10))
        self.content_frame_wrapper.bind("<Configure>", self._update_form_height)
        
        # Height multiplier for scrollable frame (adjust this value between 0.0 and 1.0)
        self.FORM_HEIGHT_MULTIPLIER = 0.451  # <-- ADJUST THIS VALUE
        
        # -- View A: Form (Scrollable) --
        self.form_frame = ctk.CTkScrollableFrame(
            self.content_frame_wrapper, 
            fg_color=("white", "#2b2b2b"),
            height=400  # Initial height, will be updated dynamically
        )
        
        # Error message label (hidden by default)
        self.lbl_error = ctk.CTkLabel(
            self.form_frame, 
            text="", 
            text_color="red",
            font=ctk.CTkFont(size=12, weight="bold"),
            wraplength=400
        )
        
        self.btn_retry = ctk.CTkButton(
            self.form_frame, text="Try again", width=110, command=self._retry_current,
            fg_color=COLORS["LIGHT_GREEN"], hover_color=COLORS["DARK_GREEN"])

        self.lbl_warning = ctk.CTkLabel(
            self.form_frame, text="", text_color="#d97706",
            font=ctk.CTkFont(size=12, weight="bold"), wraplength=400, justify="left")

        self.fields_anchor = ctk.CTkLabel(self.form_frame, text="Invoice Date (YYYY.MM.DD)")
        self.fields_anchor.pack(anchor="w", padx=15, pady=(15, 5))
        self.entry_date = ctk.CTkEntry(self.form_frame, placeholder_text="YYYY.MM.DD")
        self.entry_date.pack(fill="x", padx=15, pady=(0, 15))
        self.entry_date.bind("<KeyRelease>", self._update_preview_name)
        
        ctk.CTkLabel(self.form_frame, text="Total Value").pack(anchor="w", padx=15, pady=(5, 5))
        self.entry_value = ctk.CTkEntry(self.form_frame)
        self.entry_value.pack(fill="x", padx=15, pady=(0, 15))
        self.entry_value.bind("<KeyRelease>", self._update_preview_name)
        
        ctk.CTkLabel(self.form_frame, text="Invoice Number").pack(anchor="w", padx=15, pady=(5, 5))
        self.entry_invoice_number = ctk.CTkEntry(self.form_frame)
        self.entry_invoice_number.pack(fill="x", padx=15, pady=(0, 15))
        self.entry_invoice_number.bind("<KeyRelease>", self._update_preview_name)
        
        ctk.CTkLabel(self.form_frame, text="Supplier/Company Name").pack(anchor="w", padx=15, pady=(5, 5))
        self.entry_supplier = ctk.CTkEntry(self.form_frame)
        self.entry_supplier.pack(fill="x", padx=15, pady=(0, 15))
        self.entry_supplier.bind("<KeyRelease>", self._update_preview_name)

        self.lbl_preview_name = ctk.CTkLabel(
            self.form_frame, 
            text="Result: ...", 
            text_color=COLORS["LIGHT_GREEN"],
            justify="left",
            wraplength=400
        )
        self.lbl_preview_name.pack(pady=10, anchor="w", padx=15, fill="x")

        # -- View B: Loading --
        self.loading_frame = ctk.CTkFrame(self.content_frame_wrapper, fg_color="transparent")
        
        self.lbl_loading_icon = ctk.CTkLabel(self.loading_frame, text="") # Image container
        self.lbl_loading_icon.pack(pady=(50, 10))
        
        self.lbl_loading_text = ctk.CTkLabel(self.loading_frame, text="Reading invoice with Gemini…", text_color="gray")
        self.lbl_loading_text.pack()
        
        # Fallback Progress Bar (if no GIF)
        self.progress_bar = ctk.CTkProgressBar(self.loading_frame, width=200, mode="indeterminate")

        # Start
        self.after(POLL_MS, self._drain_ui_queue)
        if self.files:
            self._start_background_processing()
            self.load_current_invoice()
        else:
            self.lbl_filename.configure(text="No PDF files found.")

    def _load_assets(self):
        """Load GIF frames if available"""
        try:
            gif_path = get_resource_path("assets/loading.gif")
            if os.path.exists(gif_path):
                im = Image.open(gif_path)
                # Extract frames
                try:
                    while True:
                        # Resize to icon size (e.g. 80x80)
                        r = im.copy().resize((80, 80), Image.Resampling.LANCZOS)
                        self.loading_frames.append(
                            ctk.CTkImage(light_image=r, dark_image=r, size=(80, 80))
                        )
                        im.seek(len(self.loading_frames))
                except EOFError:
                    pass
        except Exception as e:
            print(f"Could not load loading animation: {e}")

    def _update_wraplengths(self, event):
        """Update wraplength for all text labels based on container width"""
        container_width = event.width*0.5 - 45
        if container_width > 100:  # Sanity check
            self.lbl_filename.configure(wraplength=container_width)
            self.lbl_preview_name.configure(wraplength=container_width)
            self.lbl_error.configure(wraplength=container_width)
            self.lbl_warning.configure(wraplength=container_width)
    
    def _update_pdf_scaling(self, event):
        """Update PDF preview scaling when container is resized"""
        container_width = event.width
        if container_width > 100 and hasattr(self.pdf_view, 'pil_images') and self.pdf_view.pil_images:
            # Calculate target width (subtract padding)
            target_width = container_width - 40
            self.pdf_view.reload_with_width(target_width)
    
    def _update_form_height(self, event):
        """Update scrollable form height based on available space"""
        available_height = event.height
        if available_height > 200:  # Sanity check
            # Calculate height using the multiplier
            form_height = int(available_height * self.FORM_HEIGHT_MULTIPLIER)
            self.form_frame.configure(height=form_height)

    def _animate(self):
        """Update loading icon"""
        if not self.loading_frames:
            return # Nothing to animate

        # If loading frame is visible, update image
        if self.lbl_loading_icon.winfo_ismapped():
            self.lbl_loading_icon.configure(image=self.loading_frames[self.loading_idx])
            self.loading_idx = (self.loading_idx + 1) % len(self.loading_frames)
            # Schedule next frame (e.g. 50ms = 20fps)
            self.animation_id = self.after(50, self._animate)

    def show_loading(self):
        """Switch content area to Loading View"""
        self.form_frame.pack_forget()
        self.loading_frame.pack(fill="both", expand=True)
        
        if self.loading_frames:
            self.progress_bar.pack_forget()
            self.lbl_loading_icon.pack(pady=(50, 10))
            if self.animation_id:
                 self.after_cancel(self.animation_id)
            self._animate()
        else:
            # Fallback
            self.lbl_loading_icon.pack_forget()
            self.progress_bar.pack(pady=(50, 10))
            self.progress_bar.start()

    def show_form(self):
        """Switch content area to Form View"""
        self.loading_frame.pack_forget()
        if self.animation_id:
            self.after_cancel(self.animation_id)
            self.animation_id = None
            
        self.form_frame.pack(fill="x", pady=10)

    def _scan_pdf_files(self):
        if not self.source_folder or not os.path.exists(self.source_folder):
            return []
        return sorted(
            (f for f in os.listdir(self.source_folder)
             if f.lower().endswith('.pdf') and not f.startswith('.')),
            key=str.lower)

    def _path(self, index):
        return os.path.join(self.source_folder, self.files[index])

    # --- Thread plumbing ---
    def _post(self, fn):
        """Run fn on the UI thread (safe to call from any thread)."""
        self.ui_queue.put(fn)

    def _drain_ui_queue(self):
        if self._closed:
            return
        try:
            while True:
                self.ui_queue.get_nowait()()
        except queue.Empty:
            pass
        self.after(POLL_MS, self._drain_ui_queue)

    def _fetch_eur_rate(self):
        self.eur_rate = CurrencyConverter.get_usd_to_eur_rate()

    # --- Extraction ---
    def _start_background_processing(self):
        for i in range(len(self.files)):
            self._submit(self._path(i))

    def _submit(self, filepath):
        if filepath in self.in_flight:
            return
        self.in_flight.add(filepath)
        self.errors.pop(filepath, None)
        self.executor.submit(self._process_file_with_gemini, filepath)

    def _process_file_with_gemini(self, filepath):
        data = self.gemini.extract_invoice_data(filepath)
        self._post(lambda: self._on_result(filepath, data))

    def _on_result(self, filepath, data):
        self.in_flight.discard(filepath)
        if 'error' in data:
            self.errors[filepath] = data['error']
        elif filepath not in self.data_cache:  # never overwrite values the user already confirmed
            self.data_cache[filepath] = data
        self._update_completion_counter()
        self._check_completion_status()
        if self.files and self._path(self.current_index) == filepath:
            self._show_current_state()

    def _retry_current(self):
        self._submit(self._path(self.current_index))
        self._show_current_state()

    def _show_current_state(self):
        filepath = self._path(self.current_index)
        if filepath in self.data_cache:
            self._populate_fields(self.data_cache[filepath])
            self.show_form()
        elif filepath in self.errors:
            self._populate_fields({'error': self.errors[filepath]})
            self.show_form()
        else:
            self.show_loading()

    def _populate_fields(self, data):
        self.lbl_error.pack_forget()
        self.btn_retry.pack_forget()
        self.lbl_warning.pack_forget()

        if 'error' in data:
            self.lbl_error.configure(
                text=f"Couldn't read this invoice: {data['error']}\n"
                     "Try again, or type the values in yourself.")
            self.lbl_error.pack(anchor="w", padx=15, pady=(15, 5), before=self.fields_anchor)
            self.btn_retry.pack(anchor="w", padx=15, pady=(0, 5), before=self.fields_anchor)
            data = {}
        elif data.get('warning'):
            self.lbl_warning.configure(text=f"⚠ {data['warning']}")
            self.lbl_warning.pack(anchor="w", padx=15, pady=(15, 0), before=self.fields_anchor)

        value = data.get('total_value')
        if isinstance(value, (int, float)):
            value = f"{value:.2f}"
        self._set_entry(self.entry_date, (data.get('date') or '').replace('-', '.'))
        self._set_entry(self.entry_invoice_number, data.get('invoice_number') or '')
        self._set_entry(self.entry_value, value or '')
        self._set_entry(self.entry_supplier, data.get('supplier') or '')
        self._update_preview_name()

    @staticmethod
    def _set_entry(entry, text):
        entry.delete(0, "end")
        if text:
            entry.insert(0, text)

    def _save_current_form(self):
        """Store whatever is in the form for the invoice on screen (user edits win)."""
        if not self.files or not self.form_frame.winfo_ismapped():
            return
        filepath = self._path(self.current_index)
        values = {
            'date': self.entry_date.get().strip(),
            'invoice_number': self.entry_invoice_number.get().strip(),
            'total_value': self.entry_value.get().strip(),
            'supplier': self.entry_supplier.get().strip(),
        }
        if filepath in self.errors and not any(values.values()):
            return  # nothing typed for a failed file; keep it as failed
        self.errors.pop(filepath, None)
        self.data_cache[filepath] = values
        self._update_completion_counter()

    def _build_filename(self, data, original_filename):
        """'<date> <value> <number> <supplier>_<original>.pdf' using the selected fields, or None."""
        parts = []
        value = data.get('total_value', '')
        if isinstance(value, (int, float)):
            value = f"{value:.2f}"
        for key, text in (('date', str(data.get('date') or '').replace('-', '.')),
                          ('value', str(value or '')),
                          ('invoice_number', str(data.get('invoice_number') or '')),
                          ('supplier', str(data.get('supplier') or ''))):
            if self.filename_fields.get(key) and text.strip():
                parts.append(text.strip())
        name = " ".join(parts)
        if self.filename_fields.get('original'):
            original = os.path.splitext(original_filename)[0]
            name = f"{name}_{original}" if name else original
        return f"{name}.pdf" if name else None

    def _update_preview_name(self, event=None):
        if not self.files:
            return
        new_name = self._build_filename({
            'date': self.entry_date.get(),
            'total_value': self.entry_value.get(),
            'invoice_number': self.entry_invoice_number.get(),
            'supplier': self.entry_supplier.get(),
        }, self.files[self.current_index])
        self.lbl_preview_name.configure(text=f"Result: {new_name or '...'}")

    def load_current_invoice(self):
        if not self.files:
            return
            
        filename = self.files[self.current_index]
        filepath = os.path.join(self.source_folder, filename)
        
        # Update Header
        self.lbl_filename.configure(text=filename)
        self.lbl_progress.configure(text=f"Invoice {self.current_index + 1} of {len(self.files)}")
        
        self._show_current_state()

        # Preview
        threading.Thread(target=self._load_preview_async, args=(filepath,), daemon=True).start()
        
        # Update Buttons
        self._update_nav_buttons()
        
        # Queue Next
        self._queue_next_files()
        
        # Check if we can already show rename all
        self._check_completion_status()

    def _update_nav_buttons(self):
        # Prev Button
        if self.current_index == 0:
            self.btn_prev.configure(state="disabled")
        else:
            self.btn_prev.configure(state="normal")
            
        # Next Button: on the last invoice it just confirms the values
        last = self.current_index == len(self.files) - 1
        self.btn_next.configure(text="Confirm" if last else "Confirm & Next")

    def _queue_next_files(self):
        # No longer needed - workers automatically pick up next files from queue
        pass

    def _load_preview_async(self, filepath):
        images = PDFService.get_pdf_images(filepath)

        def show():
            # Ignore previews that arrive after the user has moved on
            if self.files and self._path(self.current_index) == filepath:
                self.pdf_view.load_images(images)
        self._post(show)

    def next_invoice(self):
        # 1. Save State for Current File (No renaming yet)
        self._save_current_form()
        self._check_completion_status()

        # 2. Move Next
        if self.current_index < len(self.files) - 1:
            self.current_index += 1
            self.load_current_invoice()

    def _update_completion_counter(self):
        """Update the completion counter label"""
        completed = len(self.data_cache)
        total = len(self.files)
        text = f"Completed: {completed}/{total}"
        if self.errors:
            text += f" | Failed: {len(self.errors)}"
        if not self.in_flight:
            cost_eur = self.gemini.get_total_cost_usd() * (self.eur_rate or 0.92)
            text += f" | Cost: €{cost_eur:.2f}"
        self.lbl_completion.configure(text=text)

    def _check_completion_status(self):
        """Check if all files have data, show action buttons"""
        # Show the actions once nothing is still being read (failed files can be fixed by hand or skipped)
        all_processed = bool(self.files) and not self.in_flight
        if all_processed:
            # Check if buttons already packed
            if not self.btn_download_excel.winfo_ismapped():
                # Pack buttons on the right side of the frame
                self.btn_rename_all.pack(side="right")
                self.btn_download_excel.pack(side="right", padx=(0, 10))
        else:
            self.btn_download_excel.pack_forget()
            self.btn_rename_all.pack_forget()

    def download_spreadsheet(self):
        """Export invoice data to Excel"""
        self._save_current_form()
        self.btn_download_excel.configure(state="disabled", text="Exporting...")
        
        # Prepare data with original filename
        data_list = []
        for filename in self.files:
            filepath = os.path.join(self.source_folder, filename)
            if filepath in self.data_cache:
                # Add original filename to the data
                data = self.data_cache[filepath].copy()
                data['original_filename'] = filename
                data_list.append(data)
        
        # Export
        excel_path = os.path.join(self.dest_folder, "invoice_data.xlsx")
        
        # Ensure dest folder exists
        if not os.path.exists(self.dest_folder):
            os.makedirs(self.dest_folder)
            
        success = ExcelExporter.export_to_excel(data_list, excel_path)
        
        if success:
            self.btn_download_excel.configure(state="normal", text="✓ Downloaded")
        else:
            self.btn_download_excel.configure(state="normal", text="Error - Retry")

    def rename_all_files(self):
        """Batch rename all files that have values"""
        self._save_current_form()
        ready = [f for f in self.files if os.path.join(self.source_folder, f) in self.data_cache]
        missing = len(self.files) - len(ready)
        if missing and not messagebox.askyesno(
                "Some invoices have no values",
                f"{missing} invoice(s) couldn't be read and have no values, so they will be skipped.\n\n"
                "Rename the other files anyway?"):
            return
        if self.delete_original and not messagebox.askyesno(
                "Rename files",
                f"Rename {len(ready)} file(s) into:\n{self.dest_folder}\n\n"
                "The original files will be deleted after copying."):
            return

        self.btn_rename_all.configure(state="disabled", text="Processing...")
        success_count, failed = 0, []
        for filename in ready:
            filepath = os.path.join(self.source_folder, filename)
            new_name = self._build_filename(self.data_cache[filepath], filename)
            if new_name and FileManager.rename_invoice(
                    source_path=filepath, dest_folder=self.dest_folder,
                    new_filename=new_name, delete_original=self.delete_original):
                success_count += 1
            else:
                failed.append(filename)

        print(f"Batch rename complete. {success_count}/{len(self.files)} successful.")
        self.btn_rename_all.configure(state="normal", text="✓ Renamed")
        if failed:
            messagebox.showwarning("Some files were not renamed",
                                   "These files could not be renamed:\n\n" + "\n".join(failed[:15]))

    def prev_invoice(self):
        self._save_current_form()
        if self.current_index > 0:
            self.current_index -= 1
            self.load_current_invoice()
            
    def _go_home(self):
        # Kill workers
        self.executor.shutdown(wait=False, cancel_futures=True)
        if self.on_back_home:
            self.on_back_home()

    def destroy(self):
        self._closed = True
        if self.animation_id:
            self.after_cancel(self.animation_id)
        self.executor.shutdown(wait=False, cancel_futures=True)
        super().destroy()
