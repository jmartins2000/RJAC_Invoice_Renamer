"""Invoice preview with zoom: pages on a scrollable canvas.

- Pages are rendered at high resolution once, then resized for the current zoom.
- Zoom: −/+ buttons, Fit, Ctrl/⌘ + mouse wheel, double-click (fit ↔ 200%).
- Pan: drag with the mouse, wheel/trackpad (see ui/scrolling.py).
- "Open" shows the file in the computer's own viewer (always full quality).
"""
import tkinter as tk

import customtkinter as ctk
from PIL import Image, ImageTk

from src.ui import theme as t

ZOOMS = [1.0, 1.25, 1.5, 2.0, 2.5, 3.0]  # relative to "fit width"
PAD = 24   # space around pages
GAP = 16   # space between pages
MAX_FIT_WIDTH = 760


class PDFPreviewFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=t.SNOWFIELD, corner_radius=0, **kwargs)
        self.pil_images = []
        self.path = None
        self.highlight = None  # (page, (x0, y0, x1, y1) fractions) — e.g. the AT QR code
        self.zoom_i = 0
        self._photos = []
        self._last_fit = 0

        self.canvas = tk.Canvas(self, bg=t.c(t.SNOWFIELD), highlightthickness=0, bd=0, cursor="fleur")
        self.canvas._rjac_scrollable = True  # scrolled by ui/scrolling.py (both directions)
        self.vbar = ctk.CTkScrollbar(self, orientation="vertical", command=self.canvas.yview,
                                     button_color=t.FROST, button_hover_color=t.FIELD_BORDER)
        self.hbar = ctk.CTkScrollbar(self, orientation="horizontal", command=self.canvas.xview,
                                     button_color=t.FROST, button_hover_color=t.FIELD_BORDER, height=12)
        self.canvas.configure(yscrollcommand=self.vbar.set, xscrollcommand=self._xset)
        self.vbar.pack(side="right", fill="y", pady=4)
        self.canvas.pack(side="top", fill="both", expand=True)

        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<ButtonPress-1>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind("<B1-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self.canvas.bind("<Double-Button-1>", self._toggle_zoom)
        for seq in ("<Control-MouseWheel>", "<Command-MouseWheel>"):
            try:
                self.canvas.bind(seq, self._wheel_zoom)
            except tk.TclError:
                pass

        # Toolbar floating at the top right
        bar = ctk.CTkFrame(self, fg_color=t.SNOW, corner_radius=8, border_width=1, border_color=t.FROST)
        bar.place(relx=1.0, x=-22, y=10, anchor="ne")
        btn = dict(width=30, height=28, corner_radius=6, fg_color="transparent", hover_color=t.SNOWFIELD,
                   text_color=t.INK, font=t.font(15))
        ctk.CTkButton(bar, text="−", command=lambda: self.set_zoom(self.zoom_i - 1), **btn).pack(
            side="left", padx=(4, 0), pady=3)
        self.lbl_zoom = ctk.CTkLabel(bar, text="100%", width=44, font=t.font(12), text_color=t.LICHEN)
        self.lbl_zoom.pack(side="left")
        ctk.CTkButton(bar, text="+", command=lambda: self.set_zoom(self.zoom_i + 1), **btn).pack(side="left")
        ctk.CTkFrame(bar, width=1, height=18, fg_color=t.FROST).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="Fit", command=lambda: self.set_zoom(0),
                      **{**btn, "width": 36, "font": t.font(12)}).pack(side="left")
        ctk.CTkButton(bar, text="Open ↗", command=self._open,
                      **{**btn, "width": 58, "font": t.font(12)}).pack(side="left", padx=(0, 4))

    # --- public API (used by the review screen) ---
    def show_message(self, text):
        self.pil_images = []
        self._photos = []
        self.canvas.delete("all")
        self._hide_hbar()
        w, h = max(self.canvas.winfo_width(), 200), max(self.canvas.winfo_height(), 200)
        self.canvas.create_text(w / 2, 80, text=text, fill=t.c(t.LICHEN), font=(t.SANS, 13))
        self.canvas.configure(scrollregion=(0, 0, w, h))

    def set_highlight(self, page, box):
        """Outline a region of a page (fractions of the page), e.g. where the QR code was read."""
        self.highlight = (page, box) if box else None
        if self.pil_images:
            self._render(keep_view=self.zoom_i > 0, center=self._view_center())

    def load_images(self, pil_images, path=None):
        if path and path != self.path:
            self.highlight = None
        self.path = path or self.path
        self.pil_images = pil_images or []
        self.zoom_i = 0
        if not self.pil_images:
            self.show_message("No preview available for this file")
            return
        self._render(keep_view=False)

    # --- zoom ---
    def set_zoom(self, i):
        i = max(0, min(len(ZOOMS) - 1, i))
        if i == self.zoom_i or not self.pil_images:
            return
        center = self._view_center()
        if self.zoom_i == 0:
            # From "fit", zoom in on the top of the page (where invoice details usually are)
            vy = self.canvas.yview()
            center = (center[0], vy[0] + (vy[1] - vy[0]) * 0.18)
        self.zoom_i = i
        self._render(keep_view=True, center=center)

    def _toggle_zoom(self, _e):
        self.set_zoom(0 if self.zoom_i else ZOOMS.index(2.0))

    def _wheel_zoom(self, e):
        self.set_zoom(self.zoom_i + (1 if e.delta > 0 else -1))
        return "break"

    # --- drawing ---
    def _fit_width(self):
        w = self.canvas.winfo_width()
        if w <= 1:
            w = 520
        return int(min(MAX_FIT_WIDTH, max(200, w - 2 * PAD)))

    def _render(self, keep_view, center=None):
        fit = self._fit_width()
        self._last_fit = fit
        width = int(fit * ZOOMS[self.zoom_i])
        self.canvas.delete("all")
        self._photos = []
        y = PAD
        canvas_w = max(self.canvas.winfo_width(), width + 2 * PAD)
        for i, img in enumerate(self.pil_images):
            h = int(width * img.height / img.width)
            photo = ImageTk.PhotoImage(img.resize((width, h), Image.Resampling.LANCZOS))
            self._photos.append(photo)
            x = (canvas_w - width) // 2
            self.canvas.create_rectangle(x - 1, y - 1, x + width, y + h, outline=t.c(t.FROST), fill="#FFFFFF")
            self.canvas.create_image(x, y, image=photo, anchor="nw")
            if self.highlight and self.highlight[0] == i:
                self._draw_highlight(x, y, width, h, self.highlight[1])
            y += h + GAP
        self.canvas.configure(scrollregion=(0, 0, canvas_w, y + PAD - GAP))
        self.lbl_zoom.configure(text=f"{int(ZOOMS[self.zoom_i] * 100)}%")
        if keep_view and center:
            fx, fy = center
            vx, vy = self.canvas.xview(), self.canvas.yview()
            self.canvas.xview_moveto(max(0.0, fx - (vx[1] - vx[0]) / 2))
            self.canvas.yview_moveto(max(0.0, fy - (vy[1] - vy[0]) * (0.18 if fy < 0.3 else 0.5)))
        else:
            self.canvas.xview_moveto(0)
            self.canvas.yview_moveto(0)

    def _draw_highlight(self, x, y, w, h, box):
        green = t.c(t.NEEDLE)
        pad = 6
        x0, y0 = x + box[0] * w - pad, y + box[1] * h - pad
        x1, y1 = x + box[2] * w + pad, y + box[3] * h + pad
        self.canvas.create_rectangle(x0, y0, x1, y1, outline=green, width=3)
        label = "AT QR ✓"
        tag_w = 8 * len(label) + 14
        ty = y0 - 24 if y0 - 24 > y else y1 + 2
        self.canvas.create_rectangle(x0, ty, x0 + tag_w, ty + 22, outline=green, fill=green)
        self.canvas.create_text(x0 + 7, ty + 11, text=label, anchor="w", fill="#FFFFFF",
                                font=(t.SANS, 11, "bold"))

    def _view_center(self):
        x0, x1 = self.canvas.xview()
        y0, y1 = self.canvas.yview()
        return (x0 + x1) / 2, (y0 + y1) / 2

    def _on_resize(self, _e):
        if self.pil_images and abs(self._fit_width() - self._last_fit) >= 24:
            self._render(keep_view=self.zoom_i > 0, center=self._view_center())

    # --- horizontal scrollbar only when zoomed wider than the view ---
    def _xset(self, first, last):
        if float(first) <= 0.0 and float(last) >= 1.0:
            self._hide_hbar()
        elif not self.hbar.winfo_ismapped():
            self.hbar.pack(side="bottom", fill="x", padx=4, before=self.canvas)
        self.hbar.set(first, last)

    def _hide_hbar(self):
        if self.hbar.winfo_ismapped():
            self.hbar.pack_forget()

    def _open(self):
        if self.path:
            from src.ui.table import open_file
            open_file(self.path)
