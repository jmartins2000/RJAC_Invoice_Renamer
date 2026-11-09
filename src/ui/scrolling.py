"""One scroll handler for the whole app.

Tk 9 on macOS sends trackpad scrolling as <TouchpadScroll> (pixel deltas), which CustomTkinter's
scrollable frames don't listen to, and changed <MouseWheel> deltas to multiples of 120. This
handles both for every CTkScrollableFrame: the innermost one under the pointer scrolls.
ttk widgets (the History table) have their own bindings and are left alone.
"""
import sys
import tkinter
from tkinter import ttk

import customtkinter as ctk

WHEEL_STEP_PX = 48  # pixels per mouse-wheel notch


def _target(widget):
    """Innermost scrollable canvas containing `widget` (None for ttk tables)."""
    w = widget
    while w is not None:
        if isinstance(w, ttk.Treeview):
            return None
        if getattr(w, "_rjac_scrollable", False):  # e.g. the invoice preview
            return w
        if isinstance(w, ctk.CTkScrollableFrame):
            return w._parent_canvas
        w = getattr(w, "master", None)
    return None


def _extent(canvas, axis):
    region = canvas.cget("scrollregion")
    if region:
        x0, y0, x1, y1 = (float(v) for v in str(region).split())
    else:
        bbox = canvas.bbox("all")
        if not bbox:
            return 0
        x0, y0, x1, y1 = bbox
    return (x1 - x0) if axis == "x" else (y1 - y0)


def scroll_pixels(canvas, dy, dx=0):
    """Scroll content by dy (and dx) pixels; negative = down/right. Clamped."""
    for axis, d in (("y", dy), ("x", dx)):
        if not d:
            continue
        view = canvas.yview if axis == "y" else canvas.xview
        moveto = canvas.yview_moveto if axis == "y" else canvas.xview_moveto
        first, last = view()
        total = _extent(canvas, axis)
        if (first, last) == (0.0, 1.0) or total <= 0:
            continue
        moveto(max(0.0, min(1.0 - (last - first), first + d / total)))


def _widget(root, event):
    w = event.widget
    if isinstance(w, str):  # events on internal widgets arrive as path names
        try:
            w = root.nametowidget(w)
        except KeyError:
            return None
    return w


def precise_deltas(d):
    """Tk 9 TouchpadScroll %D → (dx, dy) in pixels (same as tk::PreciseScrollDeltas)."""
    dx = d >> 16
    low = d & 0xFFFF
    dy = low if low < 0x8000 else low - 0x10000
    return dx, dy


def install(root):
    # CustomTkinter's own wheel handler mis-scales Tk 9 deltas; ours replaces it.
    ctk.CTkScrollableFrame._mouse_wheel_all = lambda self, event: None

    def on_wheel(event):
        canvas = _target(_widget(root, event))
        if canvas is None:
            return
        if getattr(event, "num", None) in (4, 5):  # X11
            notches = 1 if event.num == 4 else -1
        elif abs(event.delta) >= 120 or sys.platform.startswith("win"):
            notches = event.delta / 120
        else:  # Tk 8.6 on macOS: small integer deltas
            notches = event.delta
        if event.state & 0x1:  # Shift: sideways
            scroll_pixels(canvas, 0, -notches * WHEEL_STEP_PX)
        else:
            scroll_pixels(canvas, -notches * WHEEL_STEP_PX)

    def on_touchpad(event):
        canvas = _target(_widget(root, event))
        if canvas is None:
            return
        dx, dy = precise_deltas(event.delta)
        if dx or dy:
            scroll_pixels(canvas, -dy, -dx)

    tkinter.Misc.bind_all(root, "<MouseWheel>", on_wheel, add="+")
    if not sys.platform.startswith(("win", "darwin")):
        tkinter.Misc.bind_all(root, "<Button-4>", on_wheel, add="+")
        tkinter.Misc.bind_all(root, "<Button-5>", on_wheel, add="+")
    try:
        tkinter.Misc.bind_all(root, "<TouchpadScroll>", on_touchpad, add="+")  # Tk 9+
    except tkinter.TclError:
        pass  # Tk 8.6: trackpads send <MouseWheel>
