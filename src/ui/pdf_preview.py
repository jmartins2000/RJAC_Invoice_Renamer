import customtkinter as ctk
from PIL import Image
from src.config import COLORS

class PDFPreviewFrame(ctk.CTkScrollableFrame):
    # Scaling factor for PDF images (adjust between 0.5 and 1.0)
    PDF_SCALE_FACTOR = 0.45  # <-- ADJUST THIS VALUE (lower = more zoomed out, higher = more zoomed in)
    
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.images = []
        self.image_labels = []
        self.pil_images = []  # Store original images for rescaling
        self._last_width = 0  # Track last width to avoid unnecessary reloads
        self._loading = False  # Prevent concurrent reloads

    def reload_with_width(self, target_width):
        """Reload images with a specific target width"""
        if self._loading or not self.pil_images:
            return
        
        # Only reload if width changed significantly (more than 20px difference)
        if abs(target_width - self._last_width) < 20:
            return
            
        self._loading = True
        self._display_images(target_width)
        self._loading = False

    def load_images(self, pil_images):
        """
        Display a list of PIL images stacked vertically.
        High-res images are scaled down for display while preserving quality.
        """
        # Store original images for potential rescaling
        self.pil_images = pil_images
        
        if not pil_images:
            self._clear_images()
            lbl = ctk.CTkLabel(self, text="No Preview Available", text_color="gray")
            lbl.pack(pady=20)
            self.image_labels.append(lbl)
            return

        # Get current frame width (subtract padding/scrollbar)
        # Use update_idletasks to get accurate width
        self.update_idletasks()
        frame_width = self.winfo_width()
        
        # If frame hasn't been rendered yet, use a default width
        if frame_width <= 1:
            frame_width = 450
            
        target_width = max(100, frame_width - 40)  # Leave margin for padding and scrollbar
        self._display_images(target_width)
    
    def _clear_images(self):
        """Clear existing image labels"""
        for label in self.image_labels:
            label.destroy()
        self.image_labels = []
        self.images = []
    
    def _display_images(self, target_width):
        """Display images at the specified width"""
        self._clear_images()
        
        # Apply scaling factor
        scaled_width = int(target_width * self.PDF_SCALE_FACTOR)
        self._last_width = target_width
        
        # Display new images
        for i, img in enumerate(self.pil_images):
            # Calculate proportional height
            aspect_ratio = img.size[1] / img.size[0]
            target_height = int(scaled_width * aspect_ratio)
            
            # CTkImage handles high-DPI scaling internally
            # Pass the high-res PIL image and let CTk scale it down smoothly
            ctk_img = ctk.CTkImage(
                light_image=img, 
                dark_image=img, 
                size=(scaled_width, target_height)
            )
            self.images.append(ctk_img) # Keep ref
            
            label = ctk.CTkLabel(self, image=ctk_img, text="")
            label.pack(pady=(0, 10))
            self.image_labels.append(label)

