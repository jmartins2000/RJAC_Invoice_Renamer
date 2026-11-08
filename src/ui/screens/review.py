"""Review screen: file list · PDF preview · editable fields."""
import os
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from tkinter import filedialog, messagebox

import customtkinter as ctk

from src.services.excel_exporter import ExcelExporter
from src.services.file_manager import FileManager
from src.services.gemini_service import GeminiService
from src.services.pdf_service import PDFService
from src.ui import icons, theme as t
from src.ui.pdf_preview import PDFPreviewFrame

MAX_WORKERS = 6  # parallel Gemini requests; GeminiService retries transient errors itself
POLL_MS = 100

FIELD_KEYS = ("date", "total_value", "invoice_number", "supplier")


def build_filename(data, original_filename, fields):
    """'<date> <total> <number> <supplier>_<original>.pdf' from the selected fields, or None."""
    value = data.get("total_value", "")
    if isinstance(value, (int, float)):
        value = f"{value:.2f}"
    parts = []
    for key, text in (("date", str(data.get("date") or "").replace("-", ".")),
                      ("value", str(value or "")),
                      ("invoice_number", str(data.get("invoice_number") or "")),
                      ("supplier", str(data.get("supplier") or ""))):
        text = text.strip().rstrip(". ")  # avoid "Framer B.V..pdf" and trailing dots (invalid on Windows)
        if fields.get(key) and text:
            parts.append(text)
    name = " ".join(parts)
    if fields.get("original"):
        original = os.path.splitext(original_filename)[0]
        name = f"{name}_{original}" if name else original
    return f"{FileManager._sanitize_filename(name)}.pdf" if name else None


def export_rows(rows, folder, button):
    path = filedialog.asksaveasfilename(title="Save spreadsheet", defaultextension=".xlsx",
                                        initialdir=folder, initialfile="invoice_data.xlsx",
                                        filetypes=[("Excel", "*.xlsx")])
    if path:
        ok = ExcelExporter.export_to_excel(rows, path)
        button.configure(text="✓ Exported" if ok else "Export failed")


class FileRow(ctk.CTkFrame):
    def __init__(self, master, name, on_click):
        super().__init__(master, fg_color="transparent", corner_radius=8, height=36)
        self.icon = ctk.CTkLabel(self, text="", width=18, image=icons.status("reading"))
        self.icon.pack(side="left", padx=(10, 10), pady=9)
        self.text = ctk.CTkLabel(self, text=name, font=t.font(13), text_color=t.LICHEN, anchor="w")
        self.text.pack(side="left", fill="x", expand=True, padx=(0, 10))
        for w in (self, self.icon, self.text):
            w.bind("<Button-1>", lambda _: on_click())
            w.configure(cursor="hand2")
        self._state = None
        self._selected = False

    def set_state(self, state, selected):
        if (state, selected) == (self._state, self._selected):
            return
        self._state, self._selected = state, selected
        self.icon.configure(image=icons.status(state))
        self.configure(fg_color=t.SELECTED if selected else "transparent")
        self.text.configure(text_color=t.LICHEN if state == "reading" and not selected else t.INK,
                            font=t.font(13, "bold" if selected else "normal"))


class ReviewScreen(ctk.CTkFrame):
    def __init__(self, master, api_key, source_folder, dest_folder, delete_original, filename_fields,
                 on_back, on_done):
        super().__init__(master, fg_color=t.SNOW, corner_radius=0)
        self.source_folder = source_folder
        self.dest_folder = dest_folder
        self.delete_original = delete_original
        self.filename_fields = filename_fields
        self.on_back = on_back
        self.on_done = on_done

        self.gemini = GeminiService(api_key)
        self.executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        self.ui_queue = queue.Queue()  # worker threads post callables; the UI thread runs them
        self._closed = False

        self.files = sorted((f for f in os.listdir(source_folder)
                             if f.lower().endswith(".pdf") and not f.startswith(".")), key=str.lower)
        self.current = 0
        self.extracted = {}   # path -> data from Gemini
        self.confirmed = {}   # path -> values the user confirmed (possibly edited)
        self.errors = {}      # path -> error message
        self.in_flight = set()
        self.edited = set()   # paths whose values the user changed

        self._build()
        self.after(POLL_MS, self._drain)
        for i in range(len(self.files)):
            self._submit(self._path(i))
        self._show(0)
        self._enter_bind = self.winfo_toplevel().bind("<Return>", self._on_enter, add="+")

    # ------------------------------------------------------------------ layout
    def _build(self):
        # Top bar
        bar = ctk.CTkFrame(self, fg_color=t.SNOW, corner_radius=0, height=64)
        bar.pack(fill="x")
        ctk.CTkButton(bar, text="", image=icons.line_icon("arrow_left"), width=34, height=34, corner_radius=8,
                      fg_color=t.SNOW, hover_color=t.SNOWFIELD, border_width=1, border_color=t.FROST,
                      command=self._back).pack(side="left", padx=(24, 14), pady=14)
        info = ctk.CTkFrame(bar, fg_color="transparent")
        info.pack(side="left")
        t.label(info, os.path.basename(self.source_folder) or self.source_folder, size=15,
                weight="bold").pack(anchor="w")
        prow = ctk.CTkFrame(info, fg_color="transparent")
        prow.pack(anchor="w", pady=(4, 0))
        self.progress = ctk.CTkProgressBar(prow, width=160, height=4, corner_radius=2, fg_color=t.FROST,
                                           progress_color=t.NEEDLE)
        self.progress.set(0)
        self.progress.pack(side="left", padx=(0, 10))
        self.lbl_progress = t.label(prow, "", size=12, color=t.LICHEN)
        self.lbl_progress.pack(side="left")

        self.btn_rename = t.primary_button(bar, "Rename files", command=self.rename_all, height=38, size=13)
        self.btn_rename.pack(side="right", padx=(10, 24))
        self.btn_export = t.secondary_button(bar, "Export to Excel", command=self.export_excel)
        self.btn_export.pack(side="right")
        t.divider(self).pack(fill="x")

        main = ctk.CTkFrame(self, fg_color=t.SNOW, corner_radius=0)
        main.pack(fill="both", expand=True)

        # File list
        left = ctk.CTkFrame(main, fg_color=t.SNOW, corner_radius=0, width=248)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        t.eyebrow(left, "Invoices").pack(anchor="w", padx=20, pady=(20, 8))
        self.list = ctk.CTkScrollableFrame(left, fg_color=t.SNOW, corner_radius=0,
                                           scrollbar_button_color=t.FROST,
                                           scrollbar_button_hover_color=t.FIELD_BORDER)
        self.list.pack(fill="both", expand=True, padx=(10, 0), pady=(0, 10))
        self.rows = [FileRow(self.list, name, lambda i=i: self._goto(i)) for i, name in enumerate(self.files)]
        for r in self.rows:
            r.pack(fill="x", pady=1, padx=(0, 6))
        ctk.CTkFrame(main, width=1, fg_color=t.FROST, corner_radius=0).pack(side="left", fill="y")

        # Fields panel (packed right before the preview so the preview takes the rest)
        panel = ctk.CTkFrame(main, fg_color=t.SNOW, corner_radius=0, width=340)
        panel.pack(side="right", fill="y")
        panel.pack_propagate(False)
        ctk.CTkFrame(main, width=1, fg_color=t.FROST, corner_radius=0).pack(side="right", fill="y")
        self.preview = PDFPreviewFrame(main)
        self.preview.pack(side="left", fill="both", expand=True)

        p = ctk.CTkFrame(panel, fg_color="transparent")
        p.pack(fill="both", expand=True, padx=24, pady=(24, 20))
        self.lbl_counter = t.label(p, "", size=12, color=t.LICHEN)
        self.lbl_counter.pack(anchor="w")
        self.lbl_name = t.label(p, "", size=18, weight="bold", wraplength=290)
        self.lbl_name.pack(anchor="w", fill="x", pady=(4, 0))

        self.notice = ctk.CTkFrame(p, corner_radius=10)
        self.notice_text = t.label(self.notice, "", size=13, wraplength=260)
        self.notice_text.pack(anchor="w", fill="x", padx=14, pady=(12, 12))
        self.btn_retry = t.secondary_button(self.notice, "Try again", command=self._retry, height=32)

        # Bottom nav (packed before the fields so it sticks to the bottom)
        nav = ctk.CTkFrame(p, fg_color="transparent")
        nav.pack(side="bottom", fill="x")
        self.btn_prev = ctk.CTkButton(nav, text="", image=icons.line_icon("chevron_left"), width=48, height=46,
                                      corner_radius=10, fg_color=t.SNOW, hover_color=t.SNOWFIELD,
                                      border_width=1, border_color=t.FROST, command=self.prev)
        self.btn_prev.pack(side="left", padx=(0, 10))
        self.btn_next = t.primary_button(nav, "Looks right · Next", command=self.next, height=46,
                                         image=icons.line_icon("chevron_right", 16, "#FFFFFF"), compound="right")
        self.btn_next.pack(side="left", fill="x", expand=True)

        self.form = ctk.CTkFrame(p, fg_color="transparent")
        self.form.pack(fill="x", pady=(20, 0))
        two = ctk.CTkFrame(self.form, fg_color="transparent")
        two.pack(fill="x")
        two.grid_columnconfigure((0, 1), weight=1, uniform="c")
        self.entries = {}
        for col, (key, text, ph) in enumerate((("date", "Date", "YYYY.MM.DD"), ("total_value", "Total", "0.00"))):
            box = ctk.CTkFrame(two, fg_color="transparent")
            box.grid(row=0, column=col, sticky="ew", padx=(0, 6) if col == 0 else (6, 0))
            t.label(box, text, size=12, color=t.LICHEN).pack(anchor="w", pady=(0, 6))
            self.entries[key] = t.entry(box, placeholder=ph)
            self.entries[key].pack(fill="x")
        for key, text in (("invoice_number", "Invoice number"), ("supplier", "Supplier")):
            t.label(self.form, text, size=12, color=t.LICHEN).pack(anchor="w", pady=(14, 6))
            self.entries[key] = t.entry(self.form)
            self.entries[key].pack(fill="x")
        for e in self.entries.values():
            e.bind("<KeyRelease>", lambda _: self._update_result(), add="+")

        res = ctk.CTkFrame(self.form, fg_color=t.SNOWFIELD, corner_radius=10)
        res.pack(fill="x", pady=(20, 0))
        t.eyebrow(res, "Will be saved as").pack(anchor="w", padx=16, pady=(14, 6))
        self.lbl_result = ctk.CTkLabel(res, text="", font=t.mono(13), text_color=t.INK, anchor="w",
                                       justify="left", wraplength=260)
        self.lbl_result.pack(anchor="w", fill="x", padx=16, pady=(0, 14))

        self.loading = ctk.CTkFrame(p, fg_color="transparent")
        self.loading_bar = ctk.CTkProgressBar(self.loading, mode="indeterminate", height=4, width=200,
                                              progress_color=t.NEEDLE, fg_color=t.FROST)
        self.loading_bar.pack(anchor="w", pady=(40, 12))
        t.label(self.loading, "Reading this invoice with Gemini…", size=13, color=t.LICHEN).pack(anchor="w")

    # ------------------------------------------------------------ threading
    def _post(self, fn):
        self.ui_queue.put(fn)

    def _drain(self):
        if self._closed:
            return
        try:
            while True:
                self.ui_queue.get_nowait()()
        except queue.Empty:
            pass
        self.after(POLL_MS, self._drain)

    def _path(self, i):
        return os.path.join(self.source_folder, self.files[i])

    def _submit(self, path):
        if path in self.in_flight:
            return
        self.in_flight.add(path)
        self.errors.pop(path, None)
        self.executor.submit(self._work, path)

    def _work(self, path):
        data = self.gemini.extract_invoice_data(path)
        self._post(lambda: self._on_result(path, data))

    def _on_result(self, path, data):
        self.in_flight.discard(path)
        if "error" in data:
            self.errors[path] = data["error"]
        else:
            self.extracted[path] = data
        self._refresh_status()
        if self._path(self.current) == path and path not in self.confirmed:
            self._show_values()

    def _retry(self):
        self._submit(self._path(self.current))
        self._show_values()
        self._refresh_status()

    # ------------------------------------------------------------- display
    def _state(self, path):
        if path in self.confirmed:
            return "confirmed"
        if path in self.in_flight:
            return "reading"
        if path in self.errors:
            return "error"
        data = self.extracted.get(path, {})
        if data.get("warning") or not data.get("date") or not data.get("total_value"):
            return "warning"
        return "ready"

    def _refresh_status(self):
        n = len(self.files)
        read = n - len(self.in_flight)
        attention = sum(1 for i in range(n) if self._state(self._path(i)) in ("warning", "error"))
        self.progress.set(read / n if n else 1)
        text = f"{read} of {n} read" if self.in_flight else f"All {n} read"
        if attention:
            text += f" · {attention} need{'s' if attention == 1 else ''} attention"
        self.lbl_progress.configure(text=text)
        for i, row in enumerate(self.rows):
            row.set_state(self._state(self._path(i)), i == self.current)
        renamable = sum(1 for i in range(n) if self._values_for(self._path(i)))
        self.btn_rename.configure(text=f"Rename {renamable} file{'s' if renamable != 1 else ''}",
                                  state="normal" if renamable and not self.in_flight else "disabled")

    def _show(self, i):
        self.current = i
        path = self._path(i)
        self.lbl_counter.configure(text=f"Invoice {i + 1} of {len(self.files)}")
        self.lbl_name.configure(text=self.files[i])
        last = i == len(self.files) - 1
        self.btn_next.configure(text="Looks right" if last else "Looks right · Next")
        self.btn_prev.configure(state="normal" if i > 0 else "disabled")
        self._show_values()
        self._refresh_status()
        self.preview.show_message("Loading preview…")
        threading.Thread(target=self._load_preview, args=(path,), daemon=True).start()

    def _load_preview(self, path):
        images = PDFService.get_pdf_images(path)
        self._post(lambda: self.preview.load_images(images) if self._path(self.current) == path else None)

    def _show_values(self):
        path = self._path(self.current)
        self.notice.pack_forget()
        self.btn_retry.pack_forget()
        if path in self.confirmed:
            data = self.confirmed[path]
        elif path in self.in_flight:
            self.form.pack_forget()
            self.loading.pack(fill="x")
            self.loading_bar.start()
            return
        elif path in self.errors:
            data = {}
            self._notice(f"Couldn't read this invoice: {self.errors[path]}\nTry again, or type the values yourself.",
                         error=True)
        else:
            data = self.extracted.get(path, {})
            if data.get("warning"):
                self._notice(data["warning"], error=False)
            elif not data.get("date") or not data.get("total_value"):
                self._notice("Some values couldn't be found. Please fill them in.", error=False)
        self.loading_bar.stop()
        self.loading.pack_forget()
        self.form.pack(fill="x", pady=(20, 0))
        value = data.get("total_value")
        if isinstance(value, (int, float)):
            value = f"{value:.2f}"
        values = {"date": (data.get("date") or "").replace("-", "."), "total_value": value or "",
                  "invoice_number": data.get("invoice_number") or "", "supplier": data.get("supplier") or ""}
        for key, e in self.entries.items():
            e.delete(0, "end")
            if values[key]:
                e.insert(0, values[key])
        self._update_result()

    def _notice(self, text, error):
        self.notice.configure(fg_color=t.RED_BG if error else t.AMBER_BG)
        self.notice_text.configure(text=text, text_color=t.RED if error else t.AMBER)
        self.notice.pack(fill="x", pady=(16, 0), before=self.form if self.form.winfo_ismapped() else None)
        if error:
            self.btn_retry.pack(anchor="w", padx=14, pady=(0, 12))

    def _form_values(self):
        return {k: e.get().strip() for k, e in self.entries.items()}

    def _update_result(self):
        name = build_filename(self._form_values(), self.files[self.current], self.filename_fields)
        self.lbl_result.configure(text=name or "…")

    # ------------------------------------------------------------ navigation
    def _save_current(self):
        """Keep what's in the form for the invoice on screen (user edits win)."""
        path = self._path(self.current)
        if not self.form.winfo_ismapped():
            return
        values = self._form_values()
        if not any(values.values()):
            return
        before = self.confirmed.get(path) or self._display_form(self.extracted.get(path, {}))
        if values != before:
            self.edited.add(path)
        self.confirmed[path] = values
        self.errors.pop(path, None)

    @staticmethod
    def _display_form(data):
        value = data.get("total_value")
        if isinstance(value, (int, float)):
            value = f"{value:.2f}"
        return {"date": (data.get("date") or "").replace("-", "."), "total_value": value or "",
                "invoice_number": data.get("invoice_number") or "", "supplier": data.get("supplier") or ""}

    def _goto(self, i):
        self._save_current()
        self._show(i)

    def next(self):
        self._save_current()
        if self.current < len(self.files) - 1:
            self._show(self.current + 1)
        else:
            self._refresh_status()

    def prev(self):
        self._save_current()
        if self.current > 0:
            self._show(self.current - 1)

    def _on_enter(self, _event):
        if self.winfo_ismapped():
            self.next()

    def _values_for(self, path):
        """Confirmed values, else what Gemini read (if it found anything)."""
        if path in self.confirmed:
            return self.confirmed[path]
        data = self.extracted.get(path)
        if data and not data.get("warning") and (data.get("date") or data.get("total_value")):
            return data
        return None

    # --------------------------------------------------------------- actions
    def _rows(self):
        rows = []
        for f in self.files:
            v = self._values_for(os.path.join(self.source_folder, f))
            if v:
                rows.append({**v, "original_filename": f})
        return rows

    def export_excel(self):
        self._save_current()
        export_rows(self._rows(), self.dest_folder, self.btn_export)

    def rename_all(self):
        self._save_current()
        ready = [f for f in self.files if self._values_for(os.path.join(self.source_folder, f))]
        skipped = len(self.files) - len(ready)
        msg = f"Rename {len(ready)} file{'s' if len(ready) != 1 else ''} into:\n{self.dest_folder}"
        if skipped:
            msg += f"\n\n{skipped} file{'s' if skipped != 1 else ''} without values will be skipped and left untouched."
        if self.delete_original:
            msg += "\n\nThe originals will be deleted after each copy is saved."
        if not messagebox.askokcancel("Rename files", msg):
            return
        renamed, failed = 0, []
        for f in ready:
            path = os.path.join(self.source_folder, f)
            name = build_filename(self._values_for(path), f, self.filename_fields)
            if name and FileManager.rename_invoice(path, self.dest_folder, name, self.delete_original):
                renamed += 1
            else:
                failed.append(f)
        if failed:
            messagebox.showwarning("Some files were not renamed",
                                   "These files could not be renamed:\n\n" + "\n".join(failed[:15]))
        rows, dest = self._rows(), self.dest_folder
        self.on_done(renamed=renamed, skipped=skipped, failed=len(failed), corrected=len(self.edited),
                     cost_usd=self.gemini.get_total_cost_usd(), invoices=len(self.extracted),
                     dest_folder=dest, export=lambda button: export_rows(rows, dest, button))

    def _back(self):
        if self.in_flight or self.confirmed:
            if not messagebox.askyesno("Leave this folder?", "Your checked values for this folder will be lost."):
                return
        self.on_back()

    def destroy(self):
        self._closed = True
        try:
            self.winfo_toplevel().unbind("<Return>", self._enter_bind)
        except Exception:
            pass
        self.executor.shutdown(wait=False, cancel_futures=True)
        super().destroy()
