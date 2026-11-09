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
    shot = capture_window(app)
    FeedbackDialog(app, shot, folder=getattr(app, "context_folder", None),
                   screen_name=type(getattr(app, "screen", None)).__name__)


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

        # Screenshot with drag-to-crop
        head = ctk.CTkFrame(b, fg_color="transparent")
        head.pack(fill="x", pady=(14, 6))
        t.label(head, "Screenshot", size=12, color=t.LICHEN).pack(side="left")
        self.btn_remove = t.link_button(head, "Remove", command=self._remove_shot, size=12)
        self.btn_remove.pack(side="right")
        self.btn_reset = t.link_button(head, "Use whole window", command=self._reset_crop, size=12)
        self.lbl_hint = t.label(b, "Drag on the image to send only part of it.", size=12, color=t.LICHEN)
        self.canvas = tk.Canvas(b, highlightthickness=1, highlightbackground=t.c(t.FROST), bd=0,
                                bg=t.c(t.SNOWFIELD), cursor="crosshair")
        self.canvas.pack(fill="x")
        self.lbl_hint.pack(anchor="w", pady=(4, 0))
        self.canvas.bind("<ButtonPress-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)
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
    def _draw_shot(self):
        self.canvas.delete("all")
        if self.full_shot is None:
            self.canvas.configure(height=60)
            self.canvas.create_text(PREVIEW_W // 2, 30, text="No screenshot", fill=t.c(t.LICHEN), font=(t.SANS, 12))
            self.lbl_hint.pack_forget()
            self.btn_remove.pack_forget()
            self.btn_reset.pack_forget()
            return
        img = self.shot
        self.scale = min(PREVIEW_W / img.width, 240 / img.height)
        w, h = int(img.width * self.scale), int(img.height * self.scale)
        self.canvas.configure(height=h, width=PREVIEW_W)
        self._photo = ImageTk.PhotoImage(img.resize((w, h), Image.Resampling.LANCZOS))
        self.offset = (PREVIEW_W - w) // 2
        self.canvas.create_image(self.offset, 0, image=self._photo, anchor="nw")
        self._rect = None

    def _drag_start(self, e):
        if self.shot is None:
            return
        self._start = (e.x, e.y)
        if self._rect:
            self.canvas.delete(self._rect)
        self._rect = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline=t.c(t.EVERGREEN), width=2, dash=(4, 2))

    def _drag_move(self, e):
        if self.shot is not None and self._rect:
            self.canvas.coords(self._rect, *self._start, e.x, e.y)

    def _drag_end(self, e):
        if self.shot is None or not self._rect:
            return
        x0, y0 = self._start
        x1, y1 = e.x, e.y
        if abs(x1 - x0) < 12 or abs(y1 - y0) < 12:
            self.canvas.delete(self._rect)
            self._rect = None
            return
        to_img = lambda v, off: max(0, int((v - off) / self.scale))  # noqa: E731
        box = (to_img(min(x0, x1), self.offset), to_img(min(y0, y1), 0),
               to_img(max(x0, x1), self.offset), to_img(max(y0, y1), 0))
        box = (box[0], box[1], min(box[2], self.shot.width), min(box[3], self.shot.height))
        if box[2] - box[0] > 10 and box[3] - box[1] > 10:
            self.shot = self.shot.crop(box)
            self._draw_shot()
            if not self.btn_reset.winfo_ismapped():
                self.btn_reset.pack(side="right", padx=(0, 6))

    def _reset_crop(self):
        self.shot = self.full_shot
        self._draw_shot()
        self.btn_reset.pack_forget()

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
