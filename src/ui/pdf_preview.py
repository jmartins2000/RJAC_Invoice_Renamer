import customtkinter as ctk
from PIL import Image
from src.config import COLORS

class PDFPreviewFrame(ctk.CTkScrollableFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.images = []
        self.image_labels = []

    def load_images(self, pil_images):
        """
        Display a list of PIL images stacked vertically.
        High-res images are scaled down for display while preserving quality.
        """
        # Clear existing
        for label in self.image_labels:
            label.destroy()
        self.image_labels = []
        self.images = [] # Keep reference to prevent GC

        if not pil_images:
            lbl = ctk.CTkLabel(self, text="No Preview Available", text_color="gray")
            lbl.pack(pady=20)
            return

        # Display new images
        for i, img in enumerate(pil_images):
            # Target display width (adjust based on your preview pane size)
            target_width = 550
            
            # Calculate proportional height
            aspect_ratio = img.size[1] / img.size[0]
            target_height = int(target_width * aspect_ratio)
            
            # CTkImage handles high-DPI scaling internally
            # Pass the high-res PIL image and let CTk scale it down smoothly
            ctk_img = ctk.CTkImage(
                light_image=img, 
                dark_image=img, 
                size=(target_width, target_height)
            )
            self.images.append(ctk_img) # Keep ref
            
            label = ctk.CTkLabel(self, image=ctk_img, text="")
            label.pack(pady=(0, 10))
            self.image_labels.append(label)

