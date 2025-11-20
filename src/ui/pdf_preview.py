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
            # Calculate width to fit frame (roughly) - optional logic, 
            # for now let's display at a reasonable fixed width like 500px
            # and let aspect ratio scale height
            target_width = 500
            w_percent = (target_width / float(img.size[0]))
            h_size = int((float(img.size[1]) * float(w_percent)))
            
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(target_width, h_size))
            self.images.append(ctk_img) # Keep ref
            
            label = ctk.CTkLabel(self, image=ctk_img, text="")
            label.pack(pady=(0, 10))
            self.image_labels.append(label)

