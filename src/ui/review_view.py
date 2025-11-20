import customtkinter as ctk
from PIL import Image
from src.config import COLORS
from src.services.pdf_service import PDFService
from src.services.gemini_service import GeminiService
from src.services.file_manager import FileManager
from src.ui.pdf_preview import PDFPreviewFrame
from src.utils import get_resource_path
import threading
import os
from concurrent.futures import ThreadPoolExecutor

class ReviewView(ctk.CTkFrame):
    def __init__(self, master, source_folder, dest_folder, delete_original, on_back_home):
        super().__init__(master, fg_color="transparent")
        self.source_folder = source_folder
        self.dest_folder = dest_folder
        self.delete_original = delete_original
        self.on_back_home = on_back_home
        
        # Services
        self.gemini = GeminiService()
        self.executor = ThreadPoolExecutor(max_workers=10)
        
        # State
        self.files = self._scan_pdf_files()
        self.current_index = 0
        self.data_cache = {} 
        self.active_tasks = set()
        
        # Animation State
        self.loading_frames = []
        self.loading_idx = 0
        self.animation_id = None
        self._load_assets()
        
        # Layout
        self.grid_columnconfigure(0, weight=1) # Preview
        self.grid_columnconfigure(1, weight=1) # Data
        self.grid_rowconfigure(0, weight=1)

        # --- Left: PDF Preview ---
        self.preview_container = ctk.CTkFrame(self, fg_color=("gray90", "gray20"))
        self.preview_container.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
        self.preview_container.grid_columnconfigure(0, weight=1)
        self.preview_container.grid_rowconfigure(0, weight=1)

        self.pdf_view = PDFPreviewFrame(self.preview_container, fg_color="transparent")
        self.pdf_view.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        # --- Right: Data & Controls ---
        self.data_container = ctk.CTkFrame(self, fg_color="transparent")
        self.data_container.grid(row=0, column=1, sticky="nsew")
        self.data_container.grid_columnconfigure(0, weight=1)

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
            wraplength=300
        )
        self.lbl_filename.pack(pady=(10, 5), anchor="w")
        
        self.lbl_progress = ctk.CTkLabel(self.data_container, text="Invoice 1 of X", text_color="gray")
        self.lbl_progress.pack(anchor="w", pady=(0, 20))

        # 2. Main Content Area (Swaps between Form and Loader)
        self.content_frame_wrapper = ctk.CTkFrame(self.data_container, fg_color="transparent")
        self.content_frame_wrapper.pack(fill="both", expand=True)
        
        # -- View A: Form --
        self.form_frame = ctk.CTkFrame(self.content_frame_wrapper, fg_color=("white", "#2b2b2b"))
        
        ctk.CTkLabel(self.form_frame, text="Invoice Date (YYYY-MM-DD)").pack(anchor="w", padx=15, pady=(15, 5))
        self.entry_date = ctk.CTkEntry(self.form_frame)
        self.entry_date.pack(fill="x", padx=15, pady=(0, 15))
        self.entry_date.bind("<KeyRelease>", self._update_preview_name)
        
        ctk.CTkLabel(self.form_frame, text="Total Value").pack(anchor="w", padx=15, pady=(5, 5))
        self.entry_value = ctk.CTkEntry(self.form_frame)
        self.entry_value.pack(fill="x", padx=15, pady=(0, 15))
        self.entry_value.bind("<KeyRelease>", self._update_preview_name)

        self.lbl_preview_name = ctk.CTkLabel(self.form_frame, text="Result: ...", text_color=COLORS["LIGHT_GREEN"])
        self.lbl_preview_name.pack(pady=10, anchor="w", padx=15)

        # -- View B: Loading --
        self.loading_frame = ctk.CTkFrame(self.content_frame_wrapper, fg_color="transparent")
        
        self.lbl_loading_icon = ctk.CTkLabel(self.loading_frame, text="") # Image container
        self.lbl_loading_icon.pack(pady=(50, 10))
        
        self.lbl_loading_text = ctk.CTkLabel(self.loading_frame, text="Analysing with Gemini 2.5...", text_color="gray")
        self.lbl_loading_text.pack()
        
        # Fallback Progress Bar (if no GIF)
        self.progress_bar = ctk.CTkProgressBar(self.loading_frame, width=200, mode="indeterminate")

        # 3. Navigation Buttons
        self.nav_frame = ctk.CTkFrame(self.data_container, fg_color="transparent")
        self.nav_frame.pack(fill="x", pady=20, side="bottom")

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
        
        # 4. Rename All Button (separate, below nav_frame)
        self.btn_rename_all = ctk.CTkButton(
            self.data_container,
            text="Rename All Files",
            command=self.rename_all_files,
            fg_color=COLORS["LIGHT_GREEN"],
            hover_color=COLORS["DARK_GREEN"],
            width=160
        )
        # Pack it below nav_frame, initially hidden
        # We'll pack it in _check_completion_status when ready 


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
        for i in range(min(len(self.files), 10)): # Pre-fetch up to 10 files
            filename = self.files[i]
            filepath = os.path.join(self.source_folder, filename)
            if filepath not in self.data_cache and filepath not in self.active_tasks:
                self.active_tasks.add(filepath)
                self.executor.submit(self._process_file_with_gemini, filepath)

    def _process_file_with_gemini(self, filepath):
        try:
            data = self.gemini.extract_invoice_data(filepath)
            if data:
                self.data_cache[filepath] = data
                # If current file, update UI on main thread
                if self.files and self.files[self.current_index] in filepath:
                    self.after(0, lambda: self._on_data_ready(data))
        except Exception as e:
            print(f"Error processing {filepath}: {e}")
        finally:
            if filepath in self.active_tasks:
                self.active_tasks.remove(filepath)

    def _on_data_ready(self, data):
        """Called when current file data is ready"""
        self._populate_fields(data)
        self.show_form()
        self._check_completion_status()

    def _populate_fields(self, data):
        self.entry_date.delete(0, "end")
        self.entry_date.insert(0, data.get('date', ''))
        self.entry_value.delete(0, "end")
        self.entry_value.insert(0, str(data.get('total_value', '')))
        self._update_preview_name()

    def _update_preview_name(self, event=None):
        date = self.entry_date.get().strip()
        val = self.entry_value.get().strip()
        if date and val:
            new_name = f"{date}_{val}.pdf"
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
            # Show Loading
            self.show_loading()
            
            # Trigger processing
            if filepath not in self.active_tasks:
                self.active_tasks.add(filepath)
                self.executor.submit(self._process_file_with_gemini, filepath)

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
        # Queue up to 10 files ahead
        for i in range(1, 11):
            next_idx = self.current_index + i
            if next_idx < len(self.files):
                next_file = self.files[next_idx]
                next_path = os.path.join(self.source_folder, next_file)
                if next_path not in self.data_cache and next_path not in self.active_tasks:
                     self.active_tasks.add(next_path)
                     self.executor.submit(self._process_file_with_gemini, next_path)

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
                'total_value': self.entry_value.get().strip()
            }
            self.data_cache[filepath] = current_data
        
        self._check_completion_status()

        # 2. Move Next
        if self.current_index < len(self.files) - 1:
            self.current_index += 1
            self.load_current_invoice()

    def _check_completion_status(self):
        """Check if all files have data, show Rename All button"""
        all_processed = True
        for f in self.files:
            fp = os.path.join(self.source_folder, f)
            if fp not in self.data_cache:
                all_processed = False
                break
                
        if all_processed:
            # Check if button already packed
            if not self.btn_rename_all.winfo_ismapped():
                # Pack it AFTER nav_frame (below it visually), anchored to the right
                self.btn_rename_all.pack(side="bottom", anchor="e", pady=(10, 0), after=self.nav_frame)
        else:
            self.btn_rename_all.pack_forget()

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
                
                if date_str and val_str:
                    new_name = f"{date_str}_{val_str}.pdf"
                    if FileManager.rename_invoice(
                        source_path=filepath,
                        dest_folder=self.dest_folder,
                        new_filename=new_name,
                        delete_original=self.delete_original
                    ):
                        success_count += 1
        
        # Done
        print(f"Batch rename complete. {success_count}/{len(self.files)} successful.")
        self._go_home()

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
