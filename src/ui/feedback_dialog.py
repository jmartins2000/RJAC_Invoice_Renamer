"""Feedback: a small speech-bubble button in every top bar, and the window it opens."""
import os
import subprocess
import sys
import tempfile
import tkinter as tk

import customtkinter as ctk
from PIL import Image, ImageGrab, ImageTk

from src.services import feedback
from src.ui import background, icons, theme as t

PREVIEW_W = 560


def feedback_button(parent):
    """Icon-only button for top bars (discreet; tooltip-like label on hover)."""
    b = ctk.CTkButton(parent, text="", image=icons.line_icon("chat", 16, stroke=1.8), width=34, height=34,
                      corner_radius=8, fg_color=t.SNOW, hover_color=t.SNOWFIELD, border_width=1,
                      border_color=t.FROST, command=lambda: open_feedback(parent))
    return b


def mac_screen_permission(request=False):
    """macOS only: True if this app may capture the screen (CGPreflightScreenCaptureAccess).
    With request=True, asks macOS to show its permission prompt (once)."""
    if sys.platform != "darwin":
        return True
    try:
        import ctypes
        cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        fn = cg.CGRequestScreenCaptureAccess if request else cg.CGPreflightScreenCaptureAccess
        fn.restype = ctypes.c_bool
        return bool(fn())
    except Exception:
        return True  # unknown: just try


def open_screen_settings():
    subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"])


def capture_window(win):
    """Screenshot of the app window (before the feedback window opens)."""
    win.update_idletasks()
    x, y, w, h = win.winfo_rootx(), win.winfo_rooty(), win.winfo_width(), win.winfo_height()
    try:
        if sys.platform == "darwin":  # macOS: region in points, needs Screen Recording permission once
            path = os.path.join(tempfile.mkdtemp(prefix="rjac-shot-"), "shot.png")
            subprocess.run(["screencapture", "-x", "-R", f"{x},{y},{w},{h}", path], check=True, timeout=10)
            return Image.open(path).convert("RGB")
        return ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).convert("RGB")
    except Exception as e:
        print(f"Screenshot failed: {e}")
        return None


def open_feedback(widget):
    app = widget.winfo_toplevel()
    FeedbackDialog(app, None, folder=getattr(app, "context_folder", None),
                   screen_name=type(getattr(app, "screen", None)).__name__)


class SnipOverlay(tk.Toplevel):
    """Covers the app window with a faded screenshot; drag to select the part to send."""

    def __init__(self, app, shot, on_done):
        super().__init__(app)
        self.on_done, self.shot = on_done, shot
        x, y, w, h = app.winfo_rootx(), app.winfo_rooty(), app.winfo_width(), app.winfo_height()
        self.overrideredirect(True)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.attributes("-topmost", True)
        self.w, self.h = w, h
        self.sx, self.sy = shot.width / w, shot.height / h  # screenshot pixels per window point
        self.bright = shot.resize((w, h), Image.Resampling.LANCZOS)
        faded = Image.blend(self.bright, Image.new("RGB", (w, h), (20, 30, 24)), 0.55)
        self._faded = ImageTk.PhotoImage(faded)
        self.canvas = tk.Canvas(self, width=w, height=h, highlightthickness=0, bd=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_image(0, 0, image=self._faded, anchor="nw")
        self._hint = self.canvas.create_text(
            w / 2, 28, fill="#FFFFFF", font=(t.SANS, 14, "bold"),
            text="Drag to select the part to send   ·   Enter: whole page   ·   Esc: cancel")
        self._sel = self._border = None
        self._bright_photo = None
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.bind("<Escape>", lambda e: self._finish(None))
        self.bind("<Return>", lambda e: self._finish(self.shot))
        self.after(50, self._focus)

    def _focus(self):
        try:
            self.focus_force()
            self.grab_set()
        except tk.TclError:
            pass

    def _press(self, e):
        self.start = (e.x, e.y)

    def _move(self, e):
        x0, y0 = self.start
        l, tp, r, b = min(x0, e.x), min(y0, e.y), max(x0, e.x), max(y0, e.y)
        l, tp, r, b = max(0, l), max(0, tp), min(self.w, r), min(self.h, b)
        if r - l < 2 or b - tp < 2:
            return
        self._bright_photo = ImageTk.PhotoImage(self.bright.crop((l, tp, r, b)))
        if self._sel:
            self.canvas.delete(self._sel)
            self.canvas.delete(self._border)
        self._sel = self.canvas.create_image(l, tp, image=self._bright_photo, anchor="nw")
        self._border = self.canvas.create_rectangle(l, tp, r, b, outline="#58B864", width=2)
        self.canvas.tag_raise(self._hint)

    def _release(self, e):
        x0, y0 = self.start
        l, tp, r, b = min(x0, e.x), min(y0, e.y), max(x0, e.x), max(y0, e.y)
        if r - l < 12 or b - tp < 12:
            return  # a click, not a selection
        box = (int(max(0, l) * self.sx), int(max(0, tp) * self.sy),
               int(min(self.w, r) * self.sx), int(min(self.h, b) * self.sy))
        self._finish(self.shot.crop(box))

    def _finish(self, image):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        self.on_done(image)


class FeedbackDialog(ctk.CTkToplevel):
    def __init__(self, master, screenshot, folder=None, screen_name=""):
        super().__init__(master)
        self.full_shot = screenshot
        self.shot = screenshot
        self.folder = folder if folder and os.path.isdir(folder) else None
        self.screen_name = screen_name
        self.title("Send feedback")
        self.configure(fg_color=t.SNOW)
        self.resizable(False, False)
        self.transient(master)
        w, h = 640, 760 if self.folder else 720
        sh = master.winfo_screenheight()
        h = min(h, sh - 80)
        self.geometry(f"{w}x{h}+{master.winfo_rootx() + max(0, (master.winfo_width() - w) // 2)}+{max(20, master.winfo_rooty() + 10)}")

        b = ctk.CTkFrame(self, fg_color="transparent")
        b.pack(fill="both", expand=True, padx=28, pady=22)
        t.label(b, "Send feedback", size=20, weight="bold").pack(anchor="w")
        t.label(b, "Goes privately to João, with what's needed to look into it.", size=13,
                color=t.LICHEN).pack(anchor="w", pady=(2, 14))

        self.kind = ctk.CTkSegmentedButton(
            b, values=["Report a problem", "Suggest an idea"], height=34, font=t.font(13),
            fg_color=t.SNOWFIELD, selected_color=t.EVERGREEN, selected_hover_color=t.EVERGREEN_HOVER,
            unselected_color=t.SNOWFIELD, unselected_hover_color=t.FROST, text_color=t.INK, corner_radius=8)
        self.kind.set("Report a problem")
        self.kind.pack(anchor="w")

        t.label(b, "What happened, or what would help?", size=12, color=t.LICHEN).pack(anchor="w", pady=(14, 6))
        self.text = ctk.CTkTextbox(b, height=110, wrap="word", fg_color=t.SNOW, border_width=1,
                                   border_color=t.FIELD_BORDER, corner_radius=8, text_color=t.INK, font=t.font(13))
        self.text.pack(fill="x")

        # Screenshot (optional): snip a part of the page you were on
        head = ctk.CTkFrame(b, fg_color="transparent")
        head.pack(fill="x", pady=(14, 6))
        t.label(head, "Screenshot (optional)", size=12, color=t.LICHEN).pack(side="left")
        self.btn_remove = t.link_button(head, "Remove", command=self._remove_shot, size=12)
        self.btn_retake = t.link_button(head, "Retake", command=self._take, size=12)
        self.shot_box = ctk.CTkFrame(b, fg_color="transparent")
        self.shot_box.pack(fill="x")
        self.btn_take = t.secondary_button(self.shot_box, "Take screenshot", command=self._take, height=38)
        self.canvas = tk.Canvas(self.shot_box, highlightthickness=1, highlightbackground=t.c(t.FROST), bd=0,
                                bg=t.c(t.SNOWFIELD))
        self._draw_shot()

        self.include_var = ctk.BooleanVar(value=True)
        if self.folder:
            n, size = feedback.folder_size(self.folder)
            row = ctk.CTkFrame(b, fg_color="transparent")
            row.pack(fill="x", pady=(14, 0))
            t.Toggle(row, self.include_var).pack(side="left", padx=(2, 12))
            tt = ctk.CTkFrame(row, fg_color="transparent")
            tt.pack(side="left")
            t.label(tt, f"Include this folder's invoices and data", size=14).pack(anchor="w")
            t.label(tt, f"\"{os.path.basename(self.folder)}\" · {n} file{'s' if n != 1 else ''}, "
                        f"{size / 1e6:.1f} MB · values read, runs, settings (never the API key)",
                    size=12, color=t.LICHEN).pack(anchor="w")

        self.status = t.label(b, "", size=13, color=t.LICHEN, wraplength=580)
        self.progress = ctk.CTkProgressBar(b, height=4, progress_color=t.NEEDLE, fg_color=t.FROST)
        btns = ctk.CTkFrame(b, fg_color="transparent")
        btns.pack(side="bottom", fill="x")
        self.btn_send = t.primary_button(btns, "Send", command=self._send, width=110, height=40)
        self.btn_send.pack(side="right")
        self.btn_cancel = t.secondary_button(btns, "Cancel", command=self.destroy, width=90, height=40)
        self.btn_cancel.pack(side="right", padx=10)
        self.status.pack(side="bottom", anchor="w", pady=(0, 8))
        self.after(120, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.text.focus_set()
        except Exception:
            pass

    # --- screenshot ---
    def _take(self):
        app = self.master
        if not mac_screen_permission():
            mac_screen_permission(request=True)
            self._permission_help()
            return
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.withdraw()
        app.update()
        self.after(250, lambda: self._capture(app))  # let the window disappear first

    def _capture(self, app):
        shot = capture_window(app)
        if shot is None:
            self._snipped(None, failed=True)
            return
        SnipOverlay(app, shot, self._snipped)

    def _snipped(self, image, failed=False):
        self.deiconify()
        self.lift()
        self.after(100, self._grab)
        if image is not None:
            self.full_shot = self.shot = image
        elif failed:
            self.status.configure(text="Couldn't take a screenshot on this computer.", text_color=t.AMBER)
        self._draw_shot()

    def _permission_help(self):
        self.status.configure(
            text="macOS needs to allow screenshots for this app: System Settings → Privacy & Security → Screen "
                 "Recording → turn on \"RJAC Invoice Renamer\", then reopen the app. Or attach an image instead.",
            text_color=t.AMBER)
        if not getattr(self, "_help_buttons", None):
            row = ctk.CTkFrame(self.shot_box, fg_color="transparent")
            row.pack(anchor="w", pady=(8, 0))
            t.secondary_button(row, "Open System Settings", command=open_screen_settings, height=34).pack(side="left")
            t.secondary_button(row, "Choose an image instead", command=self._choose_image, height=34).pack(
                side="left", padx=8)
            self._help_buttons = row

    def _choose_image(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self, title="Choose a screenshot",
                                          filetypes=[("Images", "*.png *.jpg *.jpeg *.webp")])
        if path:
            try:
                self.full_shot = self.shot = Image.open(path).convert("RGB")
                self.status.configure(text="")
            except Exception as e:
                self.status.configure(text=f"Couldn't open that image: {e}", text_color=t.RED)
            self._draw_shot()

    def _draw_shot(self):
        self.canvas.delete("all")
        if self.shot is None:
            self.canvas.pack_forget()
            self.btn_remove.pack_forget()
            self.btn_retake.pack_forget()
            self.btn_take.pack(anchor="w")
            return
        self.btn_take.pack_forget()
        self.canvas.pack(fill="x")
        self.btn_remove.pack(side="right")
        self.btn_retake.pack(side="right", padx=(0, 6))
        img = self.shot
        self.scale = min(PREVIEW_W / img.width, 240 / img.height)
        w, h = int(img.width * self.scale), int(img.height * self.scale)
        self.canvas.configure(height=h, width=PREVIEW_W)
        self._photo = ImageTk.PhotoImage(img.resize((w, h), Image.Resampling.LANCZOS))
        self.offset = (PREVIEW_W - w) // 2
        self.canvas.create_image(self.offset, 0, image=self._photo, anchor="nw")
        self._rect = None

    def _remove_shot(self):
        self.full_shot = self.shot = None
        self._draw_shot()

    # --- send ---
    def _send(self):
        message = self.text.get("1.0", "end").strip()
        if not message:
            self.status.configure(text="Please write a few words about it first.", text_color=t.RED)
            return
        kind = "bug" if self.kind.get().startswith("Report") else "idea"
        self.btn_send.configure(state="disabled", text="Sending…")
        self.btn_cancel.configure(state="disabled")
        self.progress.set(0)
        self.progress.pack(side="bottom", fill="x", pady=(0, 8))
        self.status.configure(text="Preparing…", text_color=t.LICHEN)
        box = background.Mailbox(self)
        shot, folder, include = self.shot, self.folder, self.include_var.get()

        def work():
            data, meta = feedback.build_package(kind, message, shot, folder, include, self.screen_name)
            box.post(lambda: self.status.configure(text=f"Sending {len(data) / 1e6:.1f} MB…"))
            try:
                return ("sent", feedback.send(data, meta, progress=lambda f: box.post(lambda: self.progress.set(f))))
            except Exception as e:
                return ("saved", feedback.save_to_desktop(data), str(e))

        background.run(self, work, self._done)

    def _done(self, result):
        if isinstance(result, Exception):
            self.status.configure(text=f"Couldn't prepare the feedback: {result}", text_color=t.RED)
            self.btn_send.configure(state="normal", text="Send")
            self.btn_cancel.configure(state="normal")
            return
        if result[0] == "sent":
            self.progress.set(1)
            self.status.configure(text="Thank you! Your feedback was sent.", text_color=t.EVERGREEN)
            self.btn_send.configure(text="Sent ✓")
            self.after(1600, self.destroy)
        else:
            self.status.configure(
                text=f"Couldn't send it (no internet?). It was saved to your Desktop as "
                     f"\"{os.path.basename(result[1])}\" — please email it to João.", text_color=t.AMBER)
            self.btn_send.configure(text="Saved to Desktop")
            self.btn_cancel.configure(state="normal", text="Close")
