"""Design tokens from the Paper design ("alpine": snow × evergreen)."""
import sys

import customtkinter as ctk

SNOW = "#FFFFFF"        # background
SNOWFIELD = "#F4F6F4"   # panels
SELECTED = "#EAF1EB"    # selected row / soft green fill
FROST = "#E3E8E4"       # lines and borders
FIELD_BORDER = "#CBD3CD"
INK = "#14231A"         # text
LICHEN = "#5E6B62"      # muted text
PLACEHOLDER = "#9AA59E"
EVERGREEN = "#204E27"   # primary
EVERGREEN_HOVER = "#2B6334"
NEEDLE = "#3D9D46"      # success / progress
AMBER = "#B45309"       # warning
AMBER_BG = "#FDF3E7"
RED = "#B42318"         # error
RED_BG = "#FDECEA"

# Native pointing-hand cursor ("hand2" is an old-style hand on macOS)
HAND = "pointinghand" if sys.platform == "darwin" else "hand2"

if sys.platform == "darwin":
    SANS, MONO = "SF Pro Text", "Menlo"
    SANS_DISPLAY = "SF Pro Display"
elif sys.platform == "win32":
    SANS, MONO = "Segoe UI", "Cascadia Mono"
    SANS_DISPLAY = "Segoe UI Semibold"
else:
    SANS, MONO, SANS_DISPLAY = "Inter", "DejaVu Sans Mono", "Inter"


def font(size=14, weight="normal", family=None):
    return ctk.CTkFont(family=family or SANS, size=size, weight=weight)


def display(size=30):
    if sys.platform == "win32":
        return ctk.CTkFont(family=SANS_DISPLAY, size=size)
    return ctk.CTkFont(family=SANS_DISPLAY, size=size, weight="bold")


def mono(size=13, weight="normal"):
    return ctk.CTkFont(family=MONO, size=size, weight=weight)


def resolve_fonts(root):
    """Fall back to installed families if the preferred ones are missing (e.g. older Windows)."""
    global SANS, MONO, SANS_DISPLAY
    import tkinter.font as tkfont
    families = set(tkfont.families(root))
    if SANS not in families:
        SANS = next((f for f in (".AppleSystemUIFont", "Helvetica Neue", "Segoe UI", "Arial") if f in families), "TkDefaultFont")
    if SANS_DISPLAY not in families:
        SANS_DISPLAY = SANS
    if MONO not in families:
        MONO = next((f for f in ("Consolas", "Menlo", "Courier New") if f in families), "TkFixedFont")


# Shared widget styles
def primary_button(parent, text, command=None, width=None, height=44, size=14, **kw):
    return ctk.CTkButton(parent, text=text, command=command, height=height, width=width or 0,
                         corner_radius=10, fg_color=EVERGREEN, hover_color=EVERGREEN_HOVER,
                         text_color=SNOW, text_color_disabled="#C9D6CB", font=font(size, "bold"), **kw)


def secondary_button(parent, text, command=None, width=None, height=38, size=13, **kw):
    return ctk.CTkButton(parent, text=text, command=command, height=height, width=width or 0,
                         corner_radius=8, fg_color=SNOW, hover_color=SNOWFIELD, border_width=1,
                         border_color=FROST, text_color=INK, font=font(size), **kw)


def link_button(parent, text, command=None, size=13, **kw):
    return ctk.CTkButton(parent, text=text, command=command, height=28, width=0, corner_radius=6,
                         fg_color="transparent", hover_color=SELECTED, text_color=EVERGREEN,
                         font=font(size, "bold"), **kw)


def label(parent, text="", size=14, color=INK, weight="normal", **kw):
    return ctk.CTkLabel(parent, text=text, text_color=color, font=font(size, weight),
                        anchor="w", justify="left", **kw)


def eyebrow(parent, text):
    """Small uppercase section label."""
    return ctk.CTkLabel(parent, text=" ".join(text.upper()) if False else text.upper(),
                        text_color=LICHEN, font=font(11, "bold"), anchor="w")


def entry(parent, placeholder="", mono_font=False, **kw):
    e = ctk.CTkEntry(parent, height=42, corner_radius=8, border_width=1, border_color=FIELD_BORDER,
                     fg_color=SNOW, text_color=INK, placeholder_text=placeholder,
                     placeholder_text_color=PLACEHOLDER,
                     font=mono(14) if mono_font else font(14), **kw)
    # Evergreen focus ring, like the design
    e.bind("<FocusIn>", lambda _: e.configure(border_color=EVERGREEN, border_width=2), add="+")
    e.bind("<FocusOut>", lambda _: e.configure(border_color=FIELD_BORDER, border_width=1), add="+")
    return e


def divider(parent):
    return ctk.CTkFrame(parent, height=1, fg_color=FROST, corner_radius=0)


class Toggle(ctk.CTkCanvas):
    """Pill switch drawn on a canvas (CTkSwitch clips on macOS)."""

    def __init__(self, parent, variable, command=None, width=40, height=24):
        super().__init__(parent, width=width, height=height, highlightthickness=0, bd=0, bg=SNOW,
                         cursor=HAND)
        self.var, self.command, self.w, self.h = variable, command, width, height
        self.bind("<Button-1>", self._click)
        self.var.trace_add("write", lambda *_: self._draw())
        self._draw()

    def _click(self, _):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

    def _draw(self):
        self.delete("all")
        w, h, on = self.w, self.h, bool(self.var.get())
        c = EVERGREEN if on else FIELD_BORDER
        r = h / 2
        self.create_oval(0, 0, h, h, fill=c, outline=c)
        self.create_oval(w - h, 0, w, h, fill=c, outline=c)
        self.create_rectangle(r, 0, w - r, h, fill=c, outline=c)
        k = 3
        x = w - h + k if on else k
        self.create_oval(x, k, x + h - 2 * k, h - k, fill=SNOW, outline=SNOW)
