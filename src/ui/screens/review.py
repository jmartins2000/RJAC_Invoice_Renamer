"""Review screen: file list · PDF preview · editable fields.

For each PDF, values come from (in order): the history (same file contents seen before),
the filename (if it follows the chosen pattern), or Gemini. Everything is saved to the
history as it happens, so leaving the screen never loses work.
"""
import os
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from tkinter import filedialog, messagebox

import customtkinter as ctk

from src.services import fields as fieldmod
from src.services import history, settings
from src.services.excel_exporter import ExcelExporter
from src.services.file_manager import FileManager
from src.services.gemini_service import GeminiService
from src.services.pdf_service import PDFService
from src.ui.feedback_dialog import feedback_button
from src.ui import icons, theme as t
from src.ui.pdf_preview import PDFPreviewFrame

MAX_WORKERS = 6  # parallel Gemini requests; GeminiService retries transient errors itself
POLL_MS = 100


def export_rows(rows, field_defs, folder, button):
    path = filedialog.asksaveasfilename(title="Save spreadsheet", defaultextension=".xlsx",
                                        initialdir=folder, initialfile="invoices.xlsx",
                                        filetypes=[("Excel", "*.xlsx")])
    if path:
        ok = ExcelExporter.export(rows, field_defs, path)
        if button is not None:
            button.configure(text="✓ Exported" if ok else "Export failed")
        return ok


class FileRow(ctk.CTkFrame):
    def __init__(self, master, name, on_click, scroller):
        super().__init__(master, fg_color="transparent", corner_radius=8, height=36)
        self.icon = ctk.CTkLabel(self, text="", width=18, image=icons.status("reading"))
        self.icon.pack(side="left", padx=(10, 10), pady=9)
        self.text = ctk.CTkLabel(self, text=name, font=t.font(13), text_color=t.LICHEN, anchor="w")
        self.text.pack(side="left", fill="x", expand=True, padx=(0, 10))
        for w in (self, self.icon, self.text):
            w.bind("<Button-1>", lambda _: on_click())
            w.configure(cursor=t.HAND)
        self._state = None
        self._selected = False

    def set_state(self, state, selected):
        if (state, selected) == (self._state, self._selected):
            return
        self._state, self._selected = state, selected
        self.icon.configure(image=icons.status("confirmed" if state == "renamed" else state))
        self.configure(fg_color=t.SELECTED if selected else "transparent")
        self.text.configure(text_color=t.LICHEN if state == "reading" and not selected else t.INK,
                            font=t.font(13, "bold" if selected else "normal"))


class RenameDialog(ctk.CTkToplevel):
    def __init__(self, master, count, skipped, already, dest_folder, on_confirm):
        super().__init__(master)
        self.on_confirm = on_confirm
        self.dest = dest_folder
        self.title("Rename files")
        self.configure(fg_color=t.SNOW)
        self.resizable(False, False)
        self.transient(master)
        w, h = 520, 330
        master.update_idletasks()
        self.geometry(f"{w}x{h}+{master.winfo_rootx() + (master.winfo_width() - w) // 2}"
                      f"+{master.winfo_rooty() + 120}")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=28, pady=24)
        t.label(body, f"Rename {count} file{'s' if count != 1 else ''}", size=20, weight="bold").pack(anchor="w")
        notes = []
        if already:
            notes.append(f"{already} already renamed or duplicates (left as they are)")
        if skipped:
            notes.append(f"{skipped} without values (skipped, left untouched)")
        if notes:
            t.label(body, " · ".join(notes), size=13, color=t.LICHEN, wraplength=460).pack(anchor="w", pady=(6, 0))

        t.eyebrow(body, "Save to").pack(anchor="w", pady=(20, 6))
        row = ctk.CTkFrame(body, fg_color=t.SNOWFIELD, corner_radius=8)
        row.pack(fill="x")
        t.link_button(row, "Change", command=self._change).pack(side="right", padx=8)
        self.lbl_dest = t.label(row, "", size=13)
        self.lbl_dest.pack(side="left", padx=14, pady=10, fill="x", expand=True)
        self._show_dest()

        tg = ctk.CTkFrame(body, fg_color="transparent")
        tg.pack(fill="x", pady=(20, 0))
        self.delete_var = ctk.BooleanVar(value=settings.load().get("delete_original", True))
        t.Toggle(tg, self.delete_var).pack(side="left", padx=(2, 12))
        tt = ctk.CTkFrame(tg, fg_color="transparent")
        tt.pack(side="left")
        t.label(tt, "Delete the originals", size=14).pack(anchor="w")
        t.label(tt, "Only after each renamed copy is saved", size=12, color=t.LICHEN).pack(anchor="w")

        btns = ctk.CTkFrame(body, fg_color="transparent")
        btns.pack(side="bottom", fill="x")
        t.primary_button(btns, "Rename", command=self._go, width=120, height=40).pack(side="right")
        t.secondary_button(btns, "Cancel", command=self.destroy, width=90, height=40).pack(side="right", padx=10)
        self.after(100, self._grab)

    def _grab(self):
        try:
            self.grab_set()
        except Exception:
            pass

    def _show_dest(self):
        from src.ui.util import shorten
        self.lbl_dest.configure(text=shorten(self.dest, 46))

    def _change(self):
        folder = filedialog.askdirectory(parent=self, title="Save renamed files to", initialdir=self.dest)
        if folder:
            self.dest = folder
            self._show_dest()

    def _go(self):
        settings.save(delete_original=self.delete_var.get())
        self.destroy()
        self.on_confirm(self.dest, self.delete_var.get())


class ReviewScreen(ctk.CTkFrame):
    def __init__(self, master, api_key, source_folder, dest_folder, on_back, on_done):
        super().__init__(master, fg_color=t.SNOW, corner_radius=0)
        self.source_folder = source_folder
        self.dest_folder = dest_folder
        self.on_back = on_back
        self.on_done = on_done

        prefs = settings.load()
        self.fields = [f for f in fieldmod.load() if f.enabled]
        self.separator = prefs.get("separator") or fieldmod.DEFAULT_SEPARATOR
        self.filename_keys = fieldmod.filename_keys(self.fields, prefs.get("filename_original"))

        self.gemini = GeminiService(api_key, field_defs=self.fields)
        self.executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        self.ui_queue = queue.Queue()  # worker threads post callables; the UI thread runs them
        self._closed = False

        from src.services.file_types import list_invoices
        self.files = list_invoices(source_folder)
        self.current = 0
        self.hashes = {}      # path -> content hash
        self.values = {}      # path -> current values (from history, filename, Gemini or the user)
        self.status = {}      # path -> read | confirmed | renamed
        self.source = {}      # path -> history | filename | gemini
        self.warnings = {}    # path -> warning text
        self.errors = {}      # path -> error message
        self.in_flight = set()
        self.edited = set()
        self.gemini_reads = 0
        self.renamed_count = 0
        self.duplicate_of = {}     # path -> filename of the identical file it duplicates (in this folder)
        self.copy_elsewhere = {}   # path -> where the already-renamed copy of this invoice is
        self.qr = {}               # path -> list of corrections made from the official QR code ([] = all matched)
        history.add_project(source_folder)
        self.run_id = history.start_run(source_folder, len(self.files))

        self._build()
        self.after(POLL_MS, self._drain)
        for i in range(len(self.files)):
            self._submit(self._path(i))
        if self.files:
            self._show(0)
        self._enter_bind = self.winfo_toplevel().bind("<Return>", self._on_enter, add="+")

    # ------------------------------------------------------------------ layout
    def _build(self):
        bar = ctk.CTkFrame(self, fg_color=t.SNOW, corner_radius=0, height=64)
        bar.pack(fill="x")
        ctk.CTkButton(bar, text="", image=icons.line_icon("arrow_left"), width=34, height=34, corner_radius=8,
                      fg_color=t.SNOW, hover_color=t.SNOWFIELD, border_width=1, border_color=t.FROST,
                      command=self.on_back).pack(side="left", padx=(24, 14), pady=14)
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
        feedback_button(bar).pack(side="right", padx=(0, 8))
        t.divider(self).pack(fill="x")

        main = ctk.CTkFrame(self, fg_color=t.SNOW, corner_radius=0)
        main.pack(fill="both", expand=True)

        left = ctk.CTkFrame(main, fg_color=t.SNOW, corner_radius=0, width=248)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        t.eyebrow(left, "Invoices").pack(anchor="w", padx=20, pady=(20, 8))
        self.list = ctk.CTkScrollableFrame(left, fg_color=t.SNOW, corner_radius=0,
                                           scrollbar_button_color=t.FROST,
                                           scrollbar_button_hover_color=t.FIELD_BORDER)
        self.list.pack(fill="both", expand=True, padx=(10, 0), pady=(0, 10))
        self.rows = [FileRow(self.list, name, lambda i=i: self._goto(i), self.list)
                     for i, name in enumerate(self.files)]
        for r in self.rows:
            r.pack(fill="x", pady=1, padx=(0, 6))
        ctk.CTkFrame(main, width=1, fg_color=t.FROST, corner_radius=0).pack(side="left", fill="y")

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

        nav = ctk.CTkFrame(p, fg_color="transparent")
        nav.pack(side="bottom", fill="x", pady=(14, 0))
        self.btn_prev = ctk.CTkButton(nav, text="", image=icons.line_icon("chevron_left"), width=48, height=46,
                                      corner_radius=10, fg_color=t.SNOW, hover_color=t.SNOWFIELD,
                                      border_width=1, border_color=t.FROST, command=self.prev)
        self.btn_prev.pack(side="left", padx=(0, 10))
        self.btn_next = t.primary_button(nav, "Looks right · Next", command=self.next, height=46,
                                         image=icons.line_icon("chevron_right", 16, "#FFFFFF"), compound="right")
        self.btn_next.pack(side="left", fill="x", expand=True)

        self.notice = ctk.CTkFrame(p, corner_radius=10)
        self.notice_text = t.label(self.notice, "", size=13, wraplength=260)
        self.notice_text.pack(anchor="w", fill="x", padx=14, pady=(12, 12))
        self.btn_retry = t.secondary_button(self.notice, "Read again with Gemini", command=self._retry, height=32)

        # Fields (scrollable when there are many)
        self.form = ctk.CTkScrollableFrame(p, fg_color=t.SNOW, corner_radius=0,
                                           scrollbar_button_color=t.FROST,
                                           scrollbar_button_hover_color=t.FIELD_BORDER)
        self.entries = {}
        grid = ctk.CTkFrame(self.form, fg_color="transparent")
        grid.pack(fill="x", padx=(0, 8))
        grid.grid_columnconfigure((0, 1), weight=1, uniform="c")
        r = c = 0
        for f in self.fields:
            half = f.type in ("date", "number")
            if not half and c == 1:
                r, c = r + 1, 0
            box = ctk.CTkFrame(grid, fg_color="transparent")
            box.grid(row=r, column=c, columnspan=1 if half else 2, sticky="ew",
                     padx=((0, 6) if c == 0 and half else (6, 0) if half else 0), pady=(0, 14))
            t.label(box, f.label, size=12, color=t.LICHEN).pack(anchor="w", pady=(0, 6))
            ph = "YYYY.MM.DD" if f.type == "date" else "0.00" if f.type == "number" else ""
            e = t.entry(box, placeholder=ph)
            e.pack(fill="x")
            e.bind("<KeyRelease>", lambda _: self._update_result(), add="+")
            self.entries[f.key] = e
            if half and c == 0:
                c = 1
            else:
                r, c = r + 1, 0
        res = ctk.CTkFrame(self.form, fg_color=t.SNOWFIELD, corner_radius=10)
        res.pack(fill="x", pady=(6, 0), padx=(0, 8))
        t.eyebrow(res, "Will be saved as").pack(anchor="w", padx=16, pady=(14, 6))
        self.lbl_result = ctk.CTkLabel(res, text="", font=t.mono(13), text_color=t.INK, anchor="w",
                                       justify="left", wraplength=250)
        self.lbl_result.pack(anchor="w", fill="x", padx=16, pady=(0, 14))

        self.loading = ctk.CTkFrame(p, fg_color="transparent")
        self.loading_bar = ctk.CTkProgressBar(self.loading, mode="indeterminate", height=4, width=200,
                                              progress_color=t.NEEDLE, fg_color=t.FROST)
        self.loading_bar.pack(anchor="w", pady=(40, 12))
        t.label(self.loading, "Reading this invoice…", size=13, color=t.LICHEN).pack(anchor="w")

    # ------------------------------------------------------------ threading
    def _post(self, fn):
        self.ui_queue.put(fn)

    def _drain(self):
        if self._closed:
            return
        while True:
            try:
                fn = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:  # one bad update must never stop the screen from processing the rest
                import traceback
                traceback.print_exc()
        self.after(POLL_MS, self._drain)

    def _path(self, i):
        return os.path.join(self.source_folder, self.files[i])

    def _submit(self, path, force_gemini=False):
        if path in self.in_flight:
            return
        self.in_flight.add(path)
        self.errors.pop(path, None)
        self.executor.submit(self._work, path, force_gemini)

    def _work(self, path, force_gemini):
        """Runs in a worker thread: history → filename → Gemini."""
        try:
            h = self.hashes.get(path) or history.fingerprint(path)
        except OSError as e:
            self._post(lambda: self._on_result(path, None, {"error": str(e)}, "gemini", None))
            return
        needed = {f.key for f in self.fields}
        if not force_gemini:
            known = history.get(h)
            if known and needed <= set(known["values"]):
                copy = os.path.join(known["folder"] or "", known["file_name"] or "")
                elsewhere = (known["status"] == "renamed" and os.path.exists(copy)
                             and os.path.abspath(copy) != os.path.abspath(path))
                self._post(lambda: self._on_result(path, h, known["values"], "history", known["status"],
                                                   copy if elsewhere else None))
                return
            parsed = fieldmod.parse_filename(os.path.basename(path), self.fields, self.filename_keys,
                                             self.separator)
            if parsed and needed <= set(parsed):
                self._post(lambda: self._on_result(path, h, parsed, "filename", "renamed"))
                return
        data = self.gemini.extract_invoice_data(path)
        self._post(lambda: self._on_result(path, h, data, "gemini", None))

    def _on_result(self, path, h, data, source, status, copy_elsewhere=None):
        self.in_flight.discard(path)
        if h:
            self.hashes[path] = h
            twin = next((p for p, x in self.hashes.items() if x == h and p != path), None)
            if twin:  # identical file already in this folder: the later name is the duplicate
                first, later = sorted([twin, path], key=lambda p: self.files.index(os.path.basename(p)))
                self.duplicate_of[later] = os.path.basename(first)
        if copy_elsewhere:
            self.copy_elsewhere[path] = copy_elsewhere
        if "error" in data:
            self.errors[path] = data["error"]
        else:
            data = dict(data)
            warning = data.pop("warning", None)
            if data.pop("qr_checked", None):
                self.qr[path] = data.pop("qr_corrected", None) or []
            data.pop("qr_corrected", None)
            if source == "gemini":
                self.gemini_reads += 1
                if not data.get("is_invoice", True):
                    warning = "This doesn't look like an invoice. Please check the values."
            data.pop("is_invoice", None)
            if warning:
                self.warnings[path] = warning
            self.values[path] = data
            self.source[path] = source
            self.status[path] = status or "read"
            if h:
                history.save(h, data, self.status[path], path,
                             model=self.gemini.model if source == "gemini" else None,
                             project=self.source_folder, run_id=self.run_id)
        self._refresh_status()
        if self.files and self._path(self.current) == path:
            self._show_values()

    def _retry(self):
        path = self._path(self.current)
        for d in (self.status, self.values, self.warnings, self.source):
            d.pop(path, None)
        self._submit(path, force_gemini=True)
        self._show_values()
        self._refresh_status()

    # ------------------------------------------------------------- display
    def _state(self, path):
        if path in self.in_flight:
            return "reading"
        if path in self.errors and path not in self.values:
            return "error"
        if path in self.duplicate_of:
            return "duplicate"
        if path in self.copy_elsewhere:
            return "renamed"
        st = self.status.get(path)
        if st in ("confirmed", "renamed"):
            return st
        v = self.values.get(path, {})
        if self.warnings.get(path) or not v.get("date") or v.get("total_value") in (None, ""):
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
        todo = len(self._renamable()[0])
        self.btn_rename.configure(text=f"Rename {todo} file{'s' if todo != 1 else ''}" if todo else "Nothing to rename",
                                  state="normal" if todo and not self.in_flight else "disabled")

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
        images = PDFService.get_pdf_images(path, target_width=760)  # sharp enough to zoom in
        self._post(lambda: self.preview.load_images(images, path) if self._path(self.current) == path else None)
        from src.services import qr_at
        qr = qr_at.read(path)  # where the official QR code is, to outline it on the preview
        if qr and qr.get("box"):
            self._post(lambda: self.preview.set_highlight(qr["page"], qr["box"])
                       if self._path(self.current) == path else None)

    def _show_values(self):
        path = self._path(self.current)
        self.notice.pack_forget()
        self.btn_retry.pack_forget()
        if path in self.in_flight:
            self.form.pack_forget()
            self.loading.pack(fill="x")
            self.loading_bar.start()
            return
        self.loading_bar.stop()
        self.loading.pack_forget()
        data = self.values.get(path, {})
        self.form.pack(fill="both", expand=True, pady=(16, 0))
        if path in self.errors and path not in self.values:
            self._notice(f"Couldn't read this invoice: {self.errors[path]}\nTry again, or type the values yourself.",
                         error=True)
        elif path in self.duplicate_of:
            self._notice(f"Duplicate: this is the same file as {self.duplicate_of[path]}. "
                         "It won't be renamed or counted twice.", error=False)
        elif path in self.copy_elsewhere:
            where = self.copy_elsewhere[path]
            self._notice(f"Already renamed: the renamed copy is in \"{os.path.basename(os.path.dirname(where))}\" "
                         f"as {os.path.basename(where)}. This original won't be renamed again.",
                         error=False, info=True)
        elif self.warnings.get(path):
            self._notice(self.warnings[path], error=False, retry=True)
        elif self.qr.get(path):
            self._notice("Corrected using the invoice's official QR code: " + "; ".join(self.qr[path]) + ".",
                         error=False, info=True)
        elif path in self.qr:
            self._notice("✓ Checked against the invoice's official QR code.", error=False, info=True)
        elif not data.get("date") or data.get("total_value") in (None, ""):
            self._notice("Some values couldn't be found. Please fill them in, or read it again.",
                         error=False, retry=True)
        elif self.source.get(path) == "history":
            when = "renamed" if self.status.get(path) == "renamed" else "read"
            self._notice(f"Already {when} before: values come from the history (no new Gemini cost).",
                         error=False, info=True, retry=True)
        elif self.source.get(path) == "filename":
            self._notice("Values taken from the filename (no Gemini cost).", error=False, info=True, retry=True)
        for f in self.fields:
            e = self.entries[f.key]
            e.delete(0, "end")
            text = fieldmod.display_value(f, data.get(f.key))
            if text:
                e.insert(0, text)
        self._update_result()

    def _notice(self, text, error, info=False, retry=None):
        bg, fg = (t.RED_BG, t.RED) if error else (t.SELECTED, t.EVERGREEN) if info else (t.AMBER_BG, t.AMBER)
        self.notice.configure(fg_color=bg)
        self.notice_text.configure(text=text, text_color=fg)
        self.notice.pack(fill="x", pady=(16, 0), before=self.form._parent_frame)  # scrollable frame packs its outer frame
        if error or retry:
            self.btn_retry.pack(anchor="w", padx=14, pady=(0, 12))

    def _form_values(self):
        return {f.key: fieldmod.parse_value(f, self.entries[f.key].get()) for f in self.fields}

    def _filename_for(self, values, original):
        return fieldmod.build_filename(values, original, self.fields, self.filename_keys, self.separator)

    def _update_result(self):
        name = self._filename_for(self._form_values(), self.files[self.current])
        self.lbl_result.configure(text=name or "…")

    # ------------------------------------------------------------ navigation
    def _save_current(self):
        """Keep what's in the form for the invoice on screen (user edits win)."""
        if not self.files or not self.form.winfo_ismapped():
            return
        path = self._path(self.current)
        vals = self._form_values()
        if not any(v not in (None, "") for v in vals.values()):
            return
        before = self.values.get(path, {})
        if any(fieldmod.display_value(f, before.get(f.key)) != fieldmod.display_value(f, vals[f.key])
               for f in self.fields):
            self.edited.add(path)
        merged = {**before, **vals}
        self.values[path] = merged
        self.errors.pop(path, None)
        self.warnings.pop(path, None)
        if self.status.get(path) != "renamed":
            self.status[path] = "confirmed"
        h = self.hashes.get(path)
        if h:
            history.save(h, merged, self.status[path], path, project=self.source_folder, run_id=self.run_id)

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
        top = self.winfo_toplevel()
        if self.winfo_ismapped() and self.focus_get() is not None and self.focus_get().winfo_toplevel() is top:
            self.next()

    def _usable(self, path):
        v = self.values.get(path)
        if not v:
            return None
        if self.status.get(path) in ("confirmed", "renamed") or (
                not self.warnings.get(path) and (v.get("date") or v.get("total_value") not in (None, ""))):
            return v
        return None

    def _renamable(self):
        """(to rename, already done, skipped) lists of filenames."""
        todo, done, skipped = [], [], []
        for f in self.files:
            path = os.path.join(self.source_folder, f)
            v = self._usable(path)
            if path in self.duplicate_of or path in self.copy_elsewhere:
                done.append(f)
            elif not v:
                skipped.append(f)
            elif self._filename_for(v, f) == f:
                done.append(f)
            else:
                todo.append(f)
        return todo, done, skipped

    # --------------------------------------------------------------- actions
    def _original_name(self, path):
        h = self.hashes.get(path)
        known = history.get(h) if h else None
        return (known or {}).get("original_name") or os.path.basename(path)

    def _rows(self):
        rows = []
        for f in self.files:
            path = os.path.join(self.source_folder, f)
            v = self._usable(path)
            if v and path not in self.duplicate_of:
                where = self.copy_elsewhere.get(path)
                rows.append({"values": v, "file_name": os.path.basename(where) if where else f,
                             "folder": os.path.dirname(where) if where else self.source_folder,
                             "original_name": self._original_name(path)})
        return rows

    def export_excel(self):
        self._save_current()
        self._refresh_status()
        export_rows(self._rows(), self.fields, self.dest_folder, self.btn_export)

    def rename_all(self):
        self._save_current()
        todo, done, skipped = self._renamable()
        RenameDialog(self.winfo_toplevel(), len(todo), len(skipped), len(done), self.dest_folder,
                     on_confirm=lambda dest, delete: self._do_rename(todo, done, skipped, dest, delete))

    def _do_rename(self, todo, done, skipped, dest, delete):
        renamed, failed, rows = 0, [], []
        for f in self.files:
            path = os.path.join(self.source_folder, f)
            v = self._usable(path)
            original = self._original_name(path)
            new_name = f
            if f in todo:
                name = self._filename_for(self.values[path], f)
                new_path = FileManager.rename_invoice(path, dest, name, delete) if name else None
                if new_path:
                    renamed += 1
                    new_name = os.path.basename(new_path)
                    h = self.hashes.get(path)
                    if h:
                        history.save(h, self.values[path], "confirmed", path, project=self.source_folder,
                                     run_id=self.run_id)
                        history.moved(h, new_path)
                else:
                    failed.append(f)
            if v and path not in self.duplicate_of:
                rows.append({"values": v, "file_name": new_name, "original_name": original,
                             "folder": dest if f in todo and f not in failed else self.source_folder})
        self.renamed_count += renamed
        if failed:
            messagebox.showwarning("Some files were not renamed",
                                   "These files could not be renamed:\n\n" + "\n".join(failed[:15]))
        fields_ = self.fields
        self.on_done(renamed=renamed, skipped=len(skipped) + len(done), failed=len(failed),
                     corrected=len(self.edited), cost_usd=self.gemini.get_total_cost_usd(),
                     invoices=self.gemini_reads, dest_folder=dest,
                     export=lambda button: export_rows(rows, fields_, dest, button))

    def destroy(self):
        if not self._closed:
            history.finish_run(self.run_id, gemini_reads=self.gemini_reads,
                               cost_usd=self.gemini.get_total_cost_usd(), renamed=self.renamed_count)
        self._closed = True
        try:
            self.winfo_toplevel().unbind("<Return>", self._enter_bind)
        except Exception:
            pass
        self.executor.shutdown(wait=False, cancel_futures=True)
        super().destroy()
