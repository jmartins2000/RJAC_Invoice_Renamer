"""Scrollable PDF page preview: white pages with a hairline border on a light panel."""
import customtkinter as ctk
from PIL import Image

from src.ui import theme as t


class PDFPreviewFrame(ctk.CTkScrollableFrame):
    MAX_PAGE_WIDTH = 620

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=t.SNOWFIELD, corner_radius=0,
                         scrollbar_button_color=t.FROST, scrollbar_button_hover_color=t.FIELD_BORDER, **kwargs)
        self.pil_images = []
        self._widgets = []
        self._refs = []
        self._width = 0
        self._message = None
        self.bind("<Configure>", self._on_resize)

    def show_message(self, text):
        self._clear()
        self.pil_images = []
        self._message = t.label(self, text, size=13, color=t.LICHEN)
        self._message.pack(pady=60)
        self._widgets.append(self._message)

    def load_images(self, pil_images):
        self.pil_images = pil_images or []
        if not self.pil_images:
            self.show_message("No preview available for this file")
            return
        self._render(self._page_width())

    def _page_width(self):
        w = self.winfo_width()
        if w <= 1:
            w = 520
        return int(min(self.MAX_PAGE_WIDTH, max(200, w - 64)))

    def _on_resize(self, _event):
        if self.pil_images:
            new = self._page_width()
            if abs(new - self._width) >= 24:
                self._render(new)

    def _clear(self):
        for w in self._widgets:
            w.destroy()
        self._widgets, self._refs = [], []

    def _render(self, width):
        self._clear()
        self._width = width
        for i, img in enumerate(self.pil_images):
            h = int(width * img.height / img.width)
            # Pre-scale to 2x display size: sharp on retina, cheap to draw.
            src = img if img.width <= width * 2 else img.resize((width * 2, h * 2), Image.Resampling.LANCZOS)
            cimg = ctk.CTkImage(light_image=src, dark_image=src, size=(width, h))
            frame = ctk.CTkFrame(self, fg_color=t.SNOW, border_width=1, border_color=t.FROST, corner_radius=4)
            frame.pack(pady=(28 if i == 0 else 0, 16))
            ctk.CTkLabel(frame, text="", image=cimg).pack(padx=1, pady=1)
            self._widgets.append(frame)
            self._refs.append(cimg)
