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
import threading
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue

# Configuration
MAX_WORKERS = 40
WORKER_LAUNCH_DELAY_MS = 150  # Delay between launching initial workers (milliseconds)

class ReviewView(ctk.CTkFrame):
    def __init__(self, master, source_folder, dest_folder, delete_original, filename_fields, on_back_home):
        super().__init__(master, fg_color="transparent")
        self.source_folder = source_folder
        self.dest_folder = dest_folder
        self.delete_original = delete_original
        self.filename_fields = filename_fields  # Dict of which fields to include
        self.on_back_home = on_back_home
        
        # Services
        self.gemini = GeminiService()
        self.executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        
        # State
        self.files = self._scan_pdf_files()
        self.current_index = 0
        self.data_cache = {} 
        self.pending_files = []  # Queue of files to process
        self.processing_count = 0  # Track active workers
        
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
        
        ctk.CTkLabel(self.form_frame, text="Invoice Date (YYYY.MM.DD)").pack(anchor="w", padx=15, pady=(15, 5))
        self.entry_date = ctk.CTkEntry(self.form_frame)
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
        
        self.lbl_loading_text = ctk.CTkLabel(self.loading_frame, text="Analysing with Gemini 2.5...", text_color="gray")
        self.lbl_loading_text.pack()
        
        # Fallback Progress Bar (if no GIF)
        self.progress_bar = ctk.CTkProgressBar(self.loading_frame, width=200, mode="indeterminate")

        # Start
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
        return [f for f in os.listdir(self.source_folder) if f.lower().endswith('.pdf')]

    def _start_background_processing(self):
        """Initialize the processing queue with all files"""
        # Build list of files to process
        self.pending_files = []
        for filename in self.files:
            filepath = os.path.join(self.source_folder, filename)
            if filepath not in self.data_cache:
                self.pending_files.append(filepath)
        
        # Start initial batch of workers with staggered delays
        for i in range(min(MAX_WORKERS, len(self.pending_files))):
            # Stagger launches to avoid rate limit burst
            delay_ms = i * WORKER_LAUNCH_DELAY_MS
            self.after(delay_ms, self._submit_next_file)

    def _submit_next_file(self):
        """Submit the next file from the queue to a worker"""
        if self.pending_files:
            filepath = self.pending_files.pop(0)
            self.processing_count += 1
            future = self.executor.submit(self._process_file_with_gemini, filepath)
            future.add_done_callback(lambda f: self._on_worker_done())

    def _on_worker_done(self):
        """Called when a worker finishes - immediately start next file"""
        self.processing_count -= 1
        self._submit_next_file()  # Keep workers busy

    def _process_file_with_gemini(self, filepath):
        data = self.gemini.extract_invoice_data(filepath)
        if data:
            self.data_cache[filepath] = data
            # Update counter regardless of current file
            self.after(0, self._update_completion_counter)
            self.after(0, self._check_completion_status)
            # If current file, update UI on main thread
            if self.files and self.files[self.current_index] in filepath:
                self.after(0, lambda d=data: self._on_data_ready(d))
        else:
            # If no data returned, it failed - still update counter
            self.after(0, self._update_completion_counter)

    def _on_data_ready(self, data):
        """Called when current file data is ready"""
        self._populate_fields(data)
        self.show_form()
        self._update_completion_counter()
        self._check_completion_status()

    def _populate_fields(self, data):
        # Check if data contains an error
        if 'error' in data:
            # Show error message in red above fields
            error_msg = data['error']
            self.lbl_error.configure(text=f"ERROR: {error_msg}")
            self.lbl_error.pack(anchor="w", padx=15, pady=(15, 10))
            
            # Fill fields with placeholder values
            self.entry_date.delete(0, "end")
            self.entry_date.insert(0, "YYYY.MM.DD")
            self.entry_invoice_number.delete(0, "end")
            self.entry_invoice_number.insert(0, "INV-XXXX")
            self.entry_value.delete(0, "end")
            self.entry_value.insert(0, "xx.xx")
            self.entry_supplier.delete(0, "end")
            self.entry_supplier.insert(0, "Wxyz")
        else:
            # Hide error label
            self.lbl_error.pack_forget()
            
            # Normal data - replace "-" with "." in date
            date_value = data.get('date', '').replace('-', '.')
            self.entry_date.delete(0, "end")
            self.entry_date.insert(0, date_value)
            self.entry_invoice_number.delete(0, "end")
            self.entry_invoice_number.insert(0, data.get('invoice_number', ''))
            self.entry_value.delete(0, "end")
            self.entry_value.insert(0, str(data.get('total_value', '')))
            self.entry_supplier.delete(0, "end")
            self.entry_supplier.insert(0, data.get('supplier', ''))
        self._update_preview_name()

    def _update_preview_name(self, event=None):
        date = self.entry_date.get().strip()
        val = self.entry_value.get().strip()
        invoice_num = self.entry_invoice_number.get().strip()
        supplier = self.entry_supplier.get().strip()
        
        # Build filename based on selected fields
        filename_parts = []
        
        if self.filename_fields.get('date') and date:
            date_formatted = date.replace('-', '.')
            filename_parts.append(date_formatted)
        
        if self.filename_fields.get('value') and val:
            filename_parts.append(val)
        
        if self.filename_fields.get('invoice_number') and invoice_num:
            filename_parts.append(invoice_num)
        
        if self.filename_fields.get('supplier') and supplier:
            filename_parts.append(supplier)
        
        # Add original filename with underscore separator if selected
        if self.filename_fields.get('original'):
            if self.files and self.current_index < len(self.files):
                original_filename = self.files[self.current_index]
                original_name_no_ext = os.path.splitext(original_filename)[0]
                if filename_parts:  # Add underscore if there are other parts
                    filename_parts.append(f"_{original_name_no_ext}")
                else:  # No underscore if it's the only field
                    filename_parts.append(original_name_no_ext)
        
        if filename_parts:
            # Join with spaces, except the original filename which already has underscore
            new_name = " ".join(filename_parts).replace(" _", "_") + ".pdf"
            self.lbl_preview_name.configure(text=f"Result: {new_name}")
        else:
            self.lbl_preview_name.configure(text="Result: ...")

    def load_current_invoice(self):
        if not self.files:
            return
            
        filename = self.files[self.current_index]
        filepath = os.path.join(self.source_folder, filename)
        
        # Update Header
        self.lbl_filename.configure(text=filename)
        self.lbl_progress.configure(text=f"Invoice {self.current_index + 1} of {len(self.files)}")
        
        # Check Cache
        if filepath in self.data_cache:
            self._populate_fields(self.data_cache[filepath])
            self.show_form()
        else:
            # Show Loading (data will arrive from background workers)
            self.show_loading()

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
            
        # Next Button
        if self.current_index == len(self.files) - 1:
             self.btn_next.configure(state="disabled")
        else:
             self.btn_next.configure(state="normal")

    def _queue_next_files(self):
        # No longer needed - workers automatically pick up next files from queue
        pass

    def _load_preview_async(self, filepath):
        try:
            images = PDFService.get_pdf_images(filepath)
            self.after(0, lambda: self.pdf_view.load_images(images))
        except Exception:
            pass

    def next_invoice(self):
        # 1. Save State for Current File (No renaming yet)
        filename = self.files[self.current_index]
        filepath = os.path.join(self.source_folder, filename)
        
        if self.form_frame.winfo_ismapped():
            current_data = {
                'date': self.entry_date.get().strip(),
                'invoice_number': self.entry_invoice_number.get().strip(),
                'total_value': self.entry_value.get().strip(),
                'supplier': self.entry_supplier.get().strip()
            }
            self.data_cache[filepath] = current_data
        
        self._check_completion_status()

        # 2. Move Next
        if self.current_index < len(self.files) - 1:
            self.current_index += 1
            self.load_current_invoice()

    def _update_completion_counter(self):
        """Update the completion counter label"""
        completed = len(self.data_cache)
        total = len(self.files)
        
        # Add cost if all completed
        if completed == total:
            cost_usd = self.gemini.get_total_cost_usd()
            cost_eur = CurrencyConverter.usd_to_eur(cost_usd)
            self.lbl_completion.configure(text=f"Completed: {completed}/{total} | Cost: €{cost_eur:.2f}")
        else:
            self.lbl_completion.configure(text=f"Completed: {completed}/{total}")

    def _check_completion_status(self):
        """Check if all files have data, show action buttons"""
        all_processed = True
        for f in self.files:
            fp = os.path.join(self.source_folder, f)
            if fp not in self.data_cache:
                all_processed = False
                break
                
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
        """Batch rename all files in cache"""
        self.btn_rename_all.configure(state="disabled", text="Processing...")
        
        success_count = 0
        for filename in self.files:
            filepath = os.path.join(self.source_folder, filename)
            if filepath in self.data_cache:
                data = self.data_cache[filepath]
                date_str = data.get('date', '')
                val_str = data.get('total_value', '')
                invoice_num_str = data.get('invoice_number', '')
                supplier_str = data.get('supplier', '')
                
                # Build filename based on selected fields
                filename_parts = []
                
                if self.filename_fields.get('date') and date_str:
                    date_formatted = date_str.replace('-', '.')
                    filename_parts.append(date_formatted)
                
                if self.filename_fields.get('value') and val_str:
                    filename_parts.append(str(val_str))
                
                if self.filename_fields.get('invoice_number') and invoice_num_str:
                    filename_parts.append(str(invoice_num_str))
                
                if self.filename_fields.get('supplier') and supplier_str:
                    filename_parts.append(str(supplier_str))
                
                # Add original filename with underscore separator if selected
                if self.filename_fields.get('original'):
                    original_name_no_ext = os.path.splitext(filename)[0]
                    if filename_parts:  # Add underscore if there are other parts
                        filename_parts.append(f"_{original_name_no_ext}")
                    else:  # No underscore if it's the only field
                        filename_parts.append(original_name_no_ext)
                
                if filename_parts:
                    # Join with spaces, except the original filename which already has underscore
                    new_name = " ".join(filename_parts).replace(" _", "_") + ".pdf"
                    if FileManager.rename_invoice(
                        source_path=filepath,
                        dest_folder=self.dest_folder,
                        new_filename=new_name,
                        delete_original=self.delete_original
                    ):
                        success_count += 1
        
        # Done
        print(f"Batch rename complete. {success_count}/{len(self.files)} successful.")
        self.btn_rename_all.configure(state="normal", text="✓ Renamed")

    def prev_invoice(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.load_current_invoice()
            
    def _go_home(self):
        # Kill workers
        self.executor.shutdown(wait=False)
        if self.on_back_home:
            self.on_back_home()

    def destroy(self):
        if self.animation_id:
            self.after_cancel(self.animation_id)
        self.executor.shutdown(wait=False)
        super().destroy()
