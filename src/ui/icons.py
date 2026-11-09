"""Line icons drawn with Pillow at 4x and scaled down, so they are crisp on any display."""
from functools import lru_cache

import customtkinter as ctk
from PIL import Image, ImageDraw

S = 4  # supersampling


def _canvas(size):
    return Image.new("RGBA", (size * S, size * S), (0, 0, 0, 0))


def _done(img, size):
    small = img.resize((size * 2, size * 2), Image.Resampling.LANCZOS)
    return ctk.CTkImage(light_image=small, dark_image=small, size=(size, size))


def _pts(points, size, box=24):
    k = size * S / box
    return [(x * k, y * k) for x, y in points]


def _w(size, stroke, box=24):
    return max(1, round(stroke * size * S / box))


@lru_cache(maxsize=None)
def status(kind, size=18):
    """kind: confirmed | ready | warning | error | reading"""
    img = _canvas(size)
    d = ImageDraw.Draw(img)
    n = size * S
    pad = S
    colors = {"confirmed": "#3D9D46", "ready": "#3D9D46", "warning": "#B45309", "error": "#B42318",
              "reading": "#CBD3CD", "duplicate": "#8A968E"}
    c = colors[kind]
    if kind in ("confirmed", "warning", "error", "duplicate"):
        d.ellipse((pad, pad, n - pad, n - pad), fill=c)
    else:
        w = round(1.5 * S)
        if kind == "reading":
            # dashed ring
            for a in range(0, 360, 40):
                d.arc((pad + w // 2, pad + w // 2, n - pad - w // 2, n - pad - w // 2), a, a + 20, fill=c, width=w)
        else:
            d.ellipse((pad + w // 2, pad + w // 2, n - pad - w // 2, n - pad - w // 2), outline=c, width=w)
    if kind == "duplicate":
        for y in (7.2, 10.8):
            d.line(_pts([(5.5, y), (12.5, y)], size, 18), fill="white", width=_w(size, 1.8, 18))
    if kind == "confirmed":
        d.line(_pts([(5.5, 9.2), (7.8, 11.4), (12.5, 6.6)], size, 18), fill="white", width=_w(size, 1.9, 18), joint="curve")
    if kind in ("warning", "error"):
        d.line(_pts([(9, 5), (9, 10)], size, 18), fill="white", width=_w(size, 1.9, 18))
        r = 1.1 * n / 18
        cx, cy = 9 * n / 18, 12.8 * n / 18
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill="white")
    return _done(img, size)


def line_icon(name, size=16, color=None, stroke=2.0):
    """Line icon; color defaults to the text colour of the current light/dark mode."""
    from src.ui import theme
    return _line_icon(name, size, theme.c(color or theme.INK), stroke)


@lru_cache(maxsize=None)
def _line_icon(name, size, color, stroke):
    img = _canvas(size)
    d = ImageDraw.Draw(img)
    w = _w(size, stroke)
    paths = {
        "arrow_left": [[(19, 12), (5, 12)], [(11, 18), (5, 12), (11, 6)]],
        "arrow_right": [[(5, 12), (19, 12)], [(13, 6), (19, 12), (13, 18)]],
        "chevron_left": [[(15, 18), (9, 12), (15, 6)]],
        "chevron_right": [[(9, 18), (15, 12), (9, 6)]],
        "check": [[(5, 12.5), (10, 17.5), (19, 7.5)]],
        "folder": [[(3, 7), (3, 18), (21, 18), (21, 9), (11.5, 9), (9.5, 6), (3, 6), (3, 7)]],
        "download": [[(12, 4), (12, 15)], [(7, 10), (12, 15), (17, 10)], [(4, 19), (20, 19)]],
    }
    if name == "folder_down":
        for p in paths["folder"]:
            d.line(_pts(p, size), fill=color, width=w, joint="curve")
        d.line(_pts([(12, 11), (12, 16)], size), fill=color, width=w)
        d.line(_pts([(9.5, 13.5), (12, 16), (14.5, 13.5)], size), fill=color, width=w, joint="curve")
    elif name == "gear":
        n = size * S
        r_out, r_in = 0.36 * n, 0.14 * n
        c = n / 2
        d.ellipse((c - r_out, c - r_out, c + r_out, c + r_out), outline=color, width=w)
        d.ellipse((c - r_in, c - r_in, c + r_in, c + r_in), outline=color, width=w)
        import math
        for i in range(8):
            a = i * math.pi / 4
            x0, y0 = c + math.cos(a) * r_out, c + math.sin(a) * r_out
            x1, y1 = c + math.cos(a) * (r_out + 0.09 * n), c + math.sin(a) * (r_out + 0.09 * n)
            d.line((x0, y0, x1, y1), fill=color, width=round(w * 1.6))
    else:
        for p in paths[name]:
            d.line(_pts(p, size), fill=color, width=w, joint="curve")
    return _done(img, size)


@lru_cache(maxsize=None)
def big_check(size=56):
    img = _canvas(size)
    d = ImageDraw.Draw(img)
    n = size * S
    d.ellipse((0, 0, n - 1, n - 1), fill="#204E27")
    d.line(_pts([(17, 28.5), (24.5, 36), (39.5, 21)], size, 56), fill="white", width=_w(size, 3.2, 56), joint="curve")
    return _done(img, size)


def tile(icon_name, filled, size=44):
    """Rounded square tile with an icon, used for the folder cards."""
    from src.ui import theme
    return _tile(icon_name, filled, size, theme.c(theme.EVERGREEN), theme.c(theme.SNOWFIELD))


@lru_cache(maxsize=None)
def _tile(icon_name, filled, size, green, panel):
    img = _canvas(size)
    d = ImageDraw.Draw(img)
    n = size * S
    d.rounded_rectangle((0, 0, n - 1, n - 1), radius=10 * S, fill=green if filled else panel)
    inner = 22
    ic = _canvas(inner)
    di = ImageDraw.Draw(ic)
    col = "#FFFFFF" if filled else green
    w = _w(inner, 1.8)
    for p in [[(3, 7), (3, 18), (21, 18), (21, 9), (11.5, 9), (9.5, 6), (3, 6), (3, 7)]]:
        di.line(_pts(p, inner), fill=col, width=w, joint="curve")
    if icon_name == "folder_down":
        di.line(_pts([(12, 11), (12, 16)], inner), fill=col, width=w)
        di.line(_pts([(9.5, 13.5), (12, 16), (14.5, 13.5)], inner), fill=col, width=w, joint="curve")
    off = (n - inner * S) // 2
    img.alpha_composite(ic, (off, off))
    return _done(img, size)


@lru_cache(maxsize=None)
def logo(size=28):
    from src.utils import get_resource_path
    img = Image.open(get_resource_path("assets/RJAC-logo.png")).convert("RGBA")
    h = round(size * img.height / img.width)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(size, h))
