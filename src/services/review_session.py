"""One review of a client folder: reading every file, keeping what the user confirms, renaming.

UI-independent (used by the HTML interface; was inside the old Tk review screen). For each file,
values come from (in order): the history (same contents seen before, re-checked against the
official AT QR), the filename (if it follows the chosen pattern), the QR alone (+ a supplier name
already known for that NIF), or Gemini. Everything is saved to the history as it happens, so
leaving never loses work. Worker threads call `on_change(path)` after each update.
"""
import os

from src.services.i18n import tr
import threading
from concurrent.futures import ThreadPoolExecutor

from src.services import fields as fieldmod
from src.services import history, qr_at, settings
from src.services.file_manager import FileManager
from src.services.file_types import list_invoices
from src.services.gemini_service import GeminiService

MAX_WORKERS = 6


class ReviewSession:
    def __init__(self, api_key, folder, dest_folder=None, on_change=None, only=None):
        self.folder = os.path.abspath(folder)
        project = history.project(self.folder) or {}
        self.dest = dest_folder or project.get("dest_folder") or self.folder
        self.on_change = on_change or (lambda path: None)
        prefs = settings.load()
        self.fields = [f for f in fieldmod.load() if f.enabled]
        self.separator = prefs.get("separator") or fieldmod.DEFAULT_SEPARATOR
        self.filename_keys = fieldmod.filename_keys(self.fields, prefs.get("filename_original"))
        self.gemini = GeminiService(api_key, field_defs=self.fields)
        self.files = list_invoices(self.folder)
        if only is not None:  # just these files (e.g. one receipt added from the e-Fatura screen)
            self.files = [f for f in self.files if f in set(only)]
        self.lock = threading.RLock()
        self.hashes, self.values, self.status, self.source = {}, {}, {}, {}
        self.warnings, self.errors, self.qr = {}, {}, {}
        self.duplicate_of, self.copy_elsewhere = {}, {}
        self.in_flight, self.edited = set(), set()
        self.gemini_reads = self.renamed_count = 0
        history.add_project(self.folder)
        self.run_id = history.start_run(self.folder, len(self.files))
        self.executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        self.closed = False
        for f in self.files:
            self.submit(self.path(f))

    # ---------------------------------------------------------------- reading
    def path(self, name):
        return os.path.join(self.folder, name)

    def submit(self, path, force_gemini=False):
        with self.lock:
            if path in self.in_flight:
                return
            self.in_flight.add(path)
            self.errors.pop(path, None)
        self.executor.submit(self._work, path, force_gemini)

    def retry(self, name):
        path = self.path(name)
        with self.lock:
            for d in (self.status, self.values, self.warnings, self.source, self.qr):
                d.pop(path, None)
        self.submit(path, force_gemini=True)
        self.on_change(path)

    def _work(self, path, force_gemini):
        try:
            self._read(path, force_gemini)
        except Exception as e:  # never leave a file stuck in "reading"
            self._result(path, None, {"error": str(e)}, "gemini", None)

    def _read(self, path, force_gemini):
        try:
            h = self.hashes.get(path) or history.fingerprint(path)
        except OSError as e:
            return self._result(path, None, {"error": str(e)}, "gemini", None)
        needed = {f.key for f in self.fields}
        if not force_gemini:
            known = history.get(h)
            if known and needed <= set(known["values"]):
                copy = os.path.join(known["folder"] or "", known["file_name"] or "")
                elsewhere = (known["status"] == "renamed" and os.path.exists(copy)
                             and os.path.abspath(copy) != os.path.abspath(path))
                values, status = dict(known["values"]), known["status"]
                if not elsewhere:  # free, local re-check against the official QR (fixes older readings)
                    qr = qr_at.read(path)
                    if qr:
                        corrected = qr_at.apply(values, self.fields, qr)
                        values["qr_checked"] = True
                        if corrected:
                            values["qr_corrected"] = corrected
                            status = "read"
                return self._result(path, h, values, "history", status, copy if elsewhere else None)
            parsed = fieldmod.parse_filename(os.path.basename(path), self.fields, self.filename_keys, self.separator)
            if parsed and needed <= set(parsed):
                return self._result(path, h, parsed, "filename", "renamed")
            qr = qr_at.read(path)  # official QR + a supplier seen before: no AI needed
            if qr:
                values = qr_at.values_without_ai(qr, self.fields, history.supplier_name_for_nif(qr.get("supplier_nif")))
                if values:
                    values["qr_checked"] = True
                    return self._result(path, h, values, "qr", None)
        data = self.gemini.extract_invoice_data(path)
        self._result(path, h, data, "gemini", None)

    def _result(self, path, h, data, source, status, copy_elsewhere=None):
        with self.lock:
            self.in_flight.discard(path)
            if h:
                self.hashes[path] = h
                twin = next((p for p, x in self.hashes.items() if x == h and p != path), None)
                if twin:  # identical file already in this folder: the later name is the duplicate
                    order = lambda p: self.files.index(os.path.basename(p)) if os.path.basename(p) in self.files else 0  # noqa: E731
                    first, later = sorted([twin, path], key=order)
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
                # A duplicate, or an original whose renamed copy lives elsewhere, must not move the
                # history's record of where that invoice is.
                if h and path not in self.copy_elsewhere and path not in self.duplicate_of:
                    history.save(h, data, self.status[path], path,
                                 model=self.gemini.model if source == "gemini" else None,
                                 project=self.folder, run_id=self.run_id, force=bool(self.qr.get(path)))
        self.on_change(path)

    # ---------------------------------------------------------------- state
    def state(self, path):
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

    def notice(self, path):
        """(kind, text, can_retry) shown above the fields, or None. kind: error | warning | info."""
        if path in self.errors and path not in self.values:
            return ("error", tr("Couldn't read this invoice: {e} Try again, or type the values yourself.", e=self.errors[path]), True)
        if path in self.duplicate_of:
            return ("warning", tr("Duplicate: this is the same file as {f}. It won't be renamed or counted twice.",
                                  f=self.duplicate_of[path]), False)
        if path in self.copy_elsewhere:
            where = self.copy_elsewhere[path]
            return ("info", tr("Already renamed: the renamed copy is in \"{folder}\" as {name}. This original won't be "
                               "renamed again.", folder=os.path.basename(os.path.dirname(where)),
                               name=os.path.basename(where)), False)
        if self.warnings.get(path):
            return ("warning", tr(self.warnings[path]), True)
        if self.source.get(path) == "qr":
            return ("info", tr("Read from the invoice's official QR code (no AI needed, no cost). "
                               "Supplier name from earlier invoices with the same NIF."), True)
        if self.qr.get(path):
            return ("info", tr("Corrected using the invoice's official QR code:") + " " + "; ".join(self.qr[path]) + ".", False)
        if path in self.qr:
            return ("info", tr("✓ Checked against the invoice's official QR code."), False)
        v = self.values.get(path, {})
        if path in self.values and (not v.get("date") or v.get("total_value") in (None, "")):
            return ("warning", tr("Some values couldn't be found. Please fill them in, or read it again."), True)
        if self.source.get(path) == "history":
            if self.status.get(path) == "renamed":
                return ("info", tr("Already renamed before: values come from the history (no new Gemini cost)."), True)
            return ("info", tr("Already read before: values come from the history (no new Gemini cost)."), True)
        if self.source.get(path) == "filename":
            return ("info", tr("Values taken from the filename (no Gemini cost)."), True)
        return None

    def filename_for(self, values, original):
        return fieldmod.build_filename(values, original, self.fields, self.filename_keys, self.separator)

    def confirm(self, name, form):
        """Keep what the user sees in the form (user edits win). form = {key: text}."""
        path = self.path(name)
        vals = {f.key: fieldmod.parse_value(f, form.get(f.key, "")) for f in self.fields}
        if not any(v not in (None, "") for v in vals.values()):
            return
        with self.lock:
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
                history.save(h, merged, self.status[path], path, project=self.folder, run_id=self.run_id)

    def usable(self, path):
        v = self.values.get(path)
        if not v:
            return None
        if self.status.get(path) in ("confirmed", "renamed") or (
                not self.warnings.get(path) and (v.get("date") or v.get("total_value") not in (None, ""))):
            return v
        return None

    def renamable(self):
        """(to rename, already done or duplicates, skipped) — lists of filenames."""
        todo, done, skipped = [], [], []
        for f in self.files:
            path = self.path(f)
            v = self.usable(path)
            if path in self.duplicate_of or path in self.copy_elsewhere:
                done.append(f)
            elif not v:
                skipped.append(f)
            elif self.filename_for(v, f) == f:
                done.append(f)
            else:
                todo.append(f)
        return todo, done, skipped

    def original_name(self, path):
        known = history.get(self.hashes[path]) if path in self.hashes else None
        return (known or {}).get("original_name") or os.path.basename(path)

    def rows(self):
        """Rows for the Excel export."""
        out = []
        for f in self.files:
            path = self.path(f)
            v = self.usable(path)
            if v and path not in self.duplicate_of:
                where = self.copy_elsewhere.get(path)
                out.append({"values": v, "file_name": os.path.basename(where) if where else f,
                            "folder": os.path.dirname(where) if where else self.folder,
                            "original_name": self.original_name(path)})
        return out

    def rename(self, dest, delete_original):
        todo, done, skipped = self.renamable()
        renamed, failed, rows = 0, [], []
        for f in self.files:
            path = self.path(f)
            v = self.usable(path)
            original = self.original_name(path)
            new_name = f
            if f in todo:
                name = self.filename_for(self.values[path], f)
                new_path = FileManager.rename_invoice(path, dest, name, delete_original) if name else None
                if new_path:
                    renamed += 1
                    new_name = os.path.basename(new_path)
                    h = self.hashes.get(path)
                    if h:
                        history.save(h, self.values[path], "confirmed", path, project=self.folder, run_id=self.run_id)
                        history.moved(h, new_path)
                else:
                    failed.append(f)
            if v and path not in self.duplicate_of:
                rows.append({"values": v, "file_name": new_name, "original_name": original,
                             "folder": dest if f in todo and f not in failed else self.folder})
        self.renamed_count += renamed
        return {"renamed": renamed, "failed": failed, "skipped": len(skipped) + len(done),
                "corrected": len(self.edited), "cost_usd": self.gemini.get_total_cost_usd(),
                "invoices": self.gemini_reads, "rows": rows}

    def close(self):
        if not self.closed:
            self.closed = True
            history.finish_run(self.run_id, gemini_reads=self.gemini_reads,
                               cost_usd=self.gemini.get_total_cost_usd(), renamed=self.renamed_count)
            self.executor.shutdown(wait=False, cancel_futures=True)
