"""The bridge between the HTML screens and the app's Python logic.

Every public method here can be called from JavaScript as `await api.name(...)` (pywebview runs
each call in its own thread) and returns plain JSON-able data. Python pushes live updates to the
page with `_emit(event, data)` → a "py" DOM event. The services (history, Gemini, QR, e-Fatura…)
are UI-independent.
"""
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import threading

import webview

from src.services import api_key as key_store
from src.services import efatura, history, models, periods, qr_at, settings, updater
from src.services import fields as fieldmod
from src.services.excel_exporter import FILE_COLUMNS, ExcelExporter
from src.services.review_session import ReviewSession
from src.version import __version__

EXAMPLE = {"date": "2026-10-06", "total_value": 60000.0, "invoice_number": "FT A/29",
           "supplier": "Quociente Invencível Lda", "supplier_nif": "517875845", "net_amount": 48780.49,
           "vat_amount": 11219.51, "vat_rate": "23%", "currency": "EUR"}
EXAMPLE_ORIGINAL = "Fatura FT A-29.pdf"
STATUS = {"read": "Check", "confirmed": "Checked", "renamed": "Renamed"}
TYPE_LABELS = {"text": "Text", "number": "Number", "date": "Date"}


def nice_path(path, parts=3):
    bits = [b for b in os.path.dirname(path).replace("\\", "/").split("/") if b]
    return " › ".join(bits[-parts:])


def open_path(path):
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def _first(chosen):
    if not chosen:
        return None
    return chosen[0] if isinstance(chosen, (list, tuple)) else chosen


def _jpeg_data_url(img, quality=85):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _filename_example(fields, include_original, separator):
    example = dict(EXAMPLE)
    for f in fields:
        example.setdefault(f.key, f.label)
    keys = fieldmod.filename_keys(fields, include_original)
    return fieldmod.build_filename(example, EXAMPLE_ORIGINAL, fields, keys, separator) or ""


class Api:
    def __init__(self):
        self._window = None
        self._session = None
        self._done = None           # last rename result (Done screen)
        self._update = None         # UpdateInfo, once found
        self._eur = 0.92
        self._ef_cache = {}
        threading.Thread(target=self._fetch_rate, daemon=True).start()

    def _fetch_rate(self):
        from src.services.currency_converter import CurrencyConverter
        self._eur = CurrencyConverter.get_usd_to_eur_rate() or 0.92

    def _emit(self, event, data=None):
        if self._window is None:
            return
        payload = json.dumps({"event": event, "data": data}, default=str)
        try:
            self._window.evaluate_js(f"window.dispatchEvent(new CustomEvent('py', {{detail: {payload}}}))")
        except Exception as e:  # window closing
            print(f"emit {event} failed: {e}")

    def _ask_folder(self, start=None):
        return _first(self._window.create_file_dialog(webview.FileDialog.FOLDER,
                                                      directory=start if start and os.path.isdir(start) else ""))

    def _ask_save(self, folder, name):
        return _first(self._window.create_file_dialog(
            webview.FileDialog.SAVE, directory=folder if folder and os.path.isdir(folder) else "",
            save_filename=name, file_types=("Excel (*.xlsx)",)))

    # ================================================================== app
    def app_info(self):
        prefs = settings.load()
        return {"version": __version__, "has_key": bool(key_store.get_api_key()),
                "appearance": prefs.get("appearance") or "system", "platform": sys.platform,
                "update": self._update_dict()}

    def start_background(self):
        """Called once by the page: warms the model list and checks for updates (packaged app only)."""
        models.warm()
        if getattr(sys, "frozen", False) or os.environ.get("RJAC_CHECK_UPDATES"):
            def check():
                info = updater.check_for_update()
                if info:
                    self._update = info
                    self._emit("update", self._update_dict())
            threading.Thread(target=check, daemon=True).start()

    def set_appearance(self, mode):
        settings.save(appearance=mode)
        return mode

    def open(self, path):
        if path and os.path.exists(path):
            open_path(path)
            return True
        return False

    def open_url(self, url):
        import webbrowser
        webbrowser.open(url)

    def copy_text(self, text):
        """Clipboard via the OS (the web view's clipboard API needs permissions)."""
        try:
            if sys.platform == "darwin":
                subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
            elif sys.platform == "win32":
                subprocess.run(["clip"], input=text.encode("utf-16-le"), check=True)
            else:
                subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=True)
            return True
        except Exception:
            return False

    # ================================================================== API key
    def check_key(self, key):
        """Validates and saves the key. Returns an error message, or None if it works."""
        from src.services.gemini_service import validate_api_key
        key = (key or "").strip()
        if not key:
            return "Paste your key in the box above."
        err = validate_api_key(key)
        if err:
            return f"That key didn't work: {err}"
        try:
            key_store.save_api_key(key)
        except Exception as e:
            return f"Couldn't save the key on this computer: {e}"
        return None

    # ================================================================== clients (folders)
    def projects(self):
        out = []
        for p in history.projects():
            out.append({
                "path": p["path"], "name": os.path.basename(p["path"]) or p["path"],
                "parent": nice_path(p["path"]),
                "exists": os.path.isdir(p["path"]), "invoices": p["invoices"], "total": round(p["total"], 2),
                "runs": p["runs"], "last_run": (p["last_run"] or "")[:10], "to_check": p["to_check"],
            })
        return out

    def new_files(self, path):
        """Number of files in the folder never read before (reads file contents, so call it lazily)."""
        return len(history.new_pdfs(path)) if os.path.isdir(path) else 0

    def add_folder(self):
        chosen = self._ask_folder()
        if not chosen:
            return None
        path = os.path.abspath(chosen)
        history.add_project(path)
        return path

    def remove_folder(self, path):
        history.remove_project(path)
        return True

    def folder(self, path):
        history.add_project(path)
        project = history.project(path) or {}
        prefs = settings.load()
        fields = [f for f in fieldmod.load() if f.enabled]
        runs = history.runs(path)
        sep = prefs.get("separator") or fieldmod.DEFAULT_SEPARATOR
        dest = project.get("dest_folder")
        return {
            "path": path, "name": os.path.basename(path) or path, "where": nice_path(path, 4),
            "exists": os.path.isdir(path),
            "periods": [{"label": p[0], "start": p[1][0], "end": p[1][1], "short": p[2]}
                        for p in periods.options(history.years(path))],
            "custom": periods.CUSTOM,
            "columns": [{"key": f.key, "label": f.label, "type": f.type} for f in fields if f.in_excel][:5],
            "runs": [{"date": (r["started_at"] or "")[:10], "reads": r["gemini_reads"] or 0,
                      "eur": round((r["cost_usd"] or 0) * self._eur, 2), "renamed": r["renamed"] or 0}
                     for r in runs],
            "example": _filename_example(fields, prefs.get("filename_original"), sep),
            "dest": dest, "dest_label": dest or "This folder (renamed in place)",
            "efatura": efatura.stored_count(path),
        }

    def folder_rows(self, path, start=None, end=None):
        fields = [f for f in fieldmod.load() if f.enabled]
        rows = history.query(start, end, path)
        out = []
        for r in rows:
            cells = {f.key: fieldmod.display_value(f, r["values"].get(f.key)) for f in fields}
            out.append({"cells": cells, "file": r["file_name"], "path": os.path.join(r["folder"] or "", r["file_name"] or ""),
                        "status": r["status"], "status_label": STATUS.get(r["status"], r["status"]),
                        "sort": {k: r["values"].get(k) for k in cells}})
        total = sum(r["values"].get("total_value") or 0 for r in rows
                    if isinstance(r["values"].get("total_value"), (int, float)))
        return {"rows": out, "total": round(total, 2)}

    def parse_dates(self, a, b):
        a, b = periods.parse_date(a), periods.parse_date(b)
        if not a or not b:
            return None
        if a > b:
            a, b = b, a
        return {"label": f"{periods.nice(a)} – {periods.nice(b)}", "start": a, "end": b, "short": f"{a} to {b}"}

    def read_button(self, path):
        """Label for the folder's main button: read N new files (with an estimated cost) or review."""
        if not os.path.isdir(path):
            return {"label": "Folder not found", "enabled": False, "new": 0}
        n = len(history.new_pdfs(path))
        if not n:
            return {"label": "Review & rename", "enabled": True, "new": 0}
        mid = settings.load().get("model") or models.default_model()
        cost = history.recent_cost_per_read() or models.cost_per_invoice(mid)
        label = f"Read {n} new file{'s' if n != 1 else ''}"
        if cost:
            label += f" · ~€{max(0.01, n * cost * self._eur):.2f}"
        return {"label": label, "enabled": True, "new": n}

    def change_dest(self, path):
        project = history.project(path) or {}
        folder = self._ask_folder(project.get("dest_folder") or path)
        if not folder:
            return None
        history.set_destination(path, folder)
        dest = None if os.path.abspath(folder) == os.path.abspath(path) else folder
        return {"dest": dest, "dest_label": dest or "This folder (renamed in place)"}

    def export_folder(self, path, start=None, end=None, short=""):
        rows = history.query(start, end, path)
        if not rows:
            return None
        project = history.project(path) or {}
        name = os.path.basename(path) + (f" – {short}" if short else "")
        out = self._ask_save(project.get("dest_folder") or path, f"{name}.xlsx")
        if not out:
            return None
        return ExcelExporter.export(rows, [f for f in fieldmod.load() if f.enabled and f.in_excel], out)

    # ================================================================== review
    def review_start(self, path):
        key = key_store.get_api_key()
        if not key:
            return {"error": "no_key"}
        self.review_close()
        session = ReviewSession(key, path, on_change=lambda p: self._emit("file", self._file_state(session, p)))
        self._session = session
        return {"name": os.path.basename(path) or path, "folder": path, "dest": session.dest,
                "fields": [{"key": f.key, "label": f.label, "type": f.type} for f in session.fields],
                "files": [self._file_state(session, session.path(f)) for f in session.files]}

    def _file_state(self, s, path):
        state = s.state(path)
        return {"name": os.path.basename(path), "state": state}

    def review_summary(self):
        s = self._session
        if not s:
            return None
        todo, done, skipped = s.renamable()
        n = len(s.files)
        attention = sum(1 for f in s.files if s.state(s.path(f)) in ("warning", "error"))
        return {"total": n, "reading": len(s.in_flight), "attention": attention, "todo": len(todo),
                "done": len(done), "skipped": len(skipped)}

    def review_file(self, name):
        s = self._session
        if not s:
            return None
        path = s.path(name)
        state = s.state(path)
        data = s.values.get(path, {})
        notice = s.notice(path) if state != "reading" else None
        form = {f.key: fieldmod.display_value(f, data.get(f.key)) for f in s.fields}
        return {"name": name, "state": state, "form": form,
                "notice": {"kind": notice[0], "text": notice[1], "retry": notice[2]} if notice else None,
                "result": s.filename_for({f.key: fieldmod.parse_value(f, form[f.key]) for f in s.fields}, name)}

    def review_preview(self, name, width=760):
        """Pages as images (sharp enough to zoom in) and where the official QR code is."""
        from src.services.pdf_service import PDFService
        s = self._session
        folder = s.folder if s else None
        path = os.path.join(folder, name) if folder else name
        return self._preview(path, width)

    def _preview(self, path, width=760, first_page_only=False):
        from src.services.pdf_service import PDFService
        if not os.path.exists(path):
            return {"pages": [], "qr": None}
        images = PDFService.get_pdf_images(path, target_width=width)
        if first_page_only:
            images = images[:1]
        pages = []
        for img in images:
            if img.width > width * 2.5:  # keep the bridge light: ~2.5× the shown width is plenty for zoom
                img = img.resize((int(width * 2.5), int(img.height * width * 2.5 / img.width)))
            pages.append({"src": _jpeg_data_url(img), "w": img.width, "h": img.height})
        qr = qr_at.read(path)
        box = {"page": qr["page"], "box": list(qr["box"])} if qr and qr.get("box") else None
        return {"pages": pages, "qr": box}

    def review_filename(self, name, form):
        s = self._session
        if not s:
            return ""
        return s.filename_for({f.key: fieldmod.parse_value(f, form.get(f.key, "")) for f in s.fields}, name) or ""

    def review_confirm(self, name, form):
        if self._session:
            self._session.confirm(name, form)
            path = self._session.path(name)
            return self._file_state(self._session, path)

    def review_retry(self, name):
        if self._session:
            self._session.retry(name)

    def review_choose_dest(self, current):
        return self._ask_folder(current)

    def review_rename_info(self):
        s = self._session
        todo, done, skipped = s.renamable()
        return {"todo": len(todo), "done": len(done), "skipped": len(skipped), "dest": s.dest,
                "delete": settings.load().get("delete_original", True)}

    def review_rename(self, dest, delete_original):
        s = self._session
        settings.save(delete_original=bool(delete_original))
        result = s.rename(dest, bool(delete_original))
        settings.add_usage(result["invoices"], result["cost_usd"])
        self._done = {"rows": result.pop("rows"), "dest": dest, "folder": s.folder}
        self.review_close()
        return {**result, "dest": dest, "dest_name": os.path.basename(dest) or dest,
                "folder": s.folder, "folder_name": os.path.basename(s.folder),
                "cost_eur": round(result["cost_usd"] * self._eur, 2)}

    def review_export(self):
        s = self._session
        if not s:
            return None
        out = self._ask_save(s.dest, "invoices.xlsx")
        return ExcelExporter.export(s.rows(), s.fields, out) if out else None

    def done_export(self):
        d = self._done
        if not d:
            return None
        out = self._ask_save(d["dest"], "invoices.xlsx")
        return ExcelExporter.export(d["rows"], [f for f in fieldmod.load() if f.enabled], out) if out else None

    def review_close(self):
        if self._session:
            self._session.close()
            self._session = None

    # ================================================================== settings
    def settings_info(self):
        key = key_store.get_api_key()
        prefs = settings.load()
        u = settings.month_usage()
        on = [f.label for f in fieldmod.load() if f.enabled]
        masked = (f"{key[:4]}{'•' * 24}{key[-4:]}" if len(key) > 10 else "•" * len(key)) if key else ""
        return {"key": masked, "has_key": bool(key), "version": __version__,
                "usage": f"This month: €{u['cost_usd'] * self._eur:.2f} · {u['invoices']} invoices",
                "fields": f"Reading: {', '.join(on)} · separator \"{prefs.get('separator') or fieldmod.DEFAULT_SEPARATOR}\"",
                "appearance": prefs.get("appearance") or "system"}

    def _model_dict(self, info):
        per100 = f"€{info.cost * 100 * self._eur:.2f} per 100 invoices" if info.cost is not None else "price unknown"
        bits = [f"Tested on sample invoices: {info.tested} fully correct" if info.tested else "Not tested yet"]
        if info.later:
            cost, when = info.later
            bits.append(f"rises to €{cost * 100 * self._eur:.2f} per 100 on {when.day} {when.strftime('%b %Y')}")
        if info.note:
            bits.append(info.note)
        return {"id": info.id, "label": info.label, "tag": info.tag or "", "price": per100, "detail": " · ".join(bits)}

    def models_list(self):
        current = settings.load().get("model") or models.default_model()
        try:
            result = models.available(key_store.get_api_key()) or []
        except Exception:
            result = []
        if not result:
            return {"current": current, "models": [self._model_dict(models.describe(current))], "error":
                    "Couldn't load the list of models (check the API key or internet)."}
        if current not in [m.id for m in result]:
            result.insert(0, models.describe(current))
        return {"current": current, "models": [self._model_dict(m) for m in result], "error": None}

    def choose_model(self, model_id):
        previous = settings.load().get("model") or models.default_model()
        err = models.probe(key_store.get_api_key(), model_id)
        if err:
            return f"{models.label(model_id)} can't be used: {err} Kept {models.label(previous)}."
        settings.save(model=model_id)
        return None

    def check_update(self):
        info = updater.check_for_update()
        if info:
            self._update = info
        return self._update_dict() if info else None

    def _update_dict(self):
        i = self._update
        return {"version": i.version, "notes": i.notes or "Improvements and fixes.",
                "direct": bool(i.asset_url)} if i else None

    def update_install(self):
        """Downloads (progress events) and starts the installer. Returns what to tell the user."""
        info = self._update
        if not info:
            return {"error": "No update found."}
        if not info.asset_url:
            self.open_url(info.page_url)
            return {"message": "The download page was opened in your browser."}
        try:
            path = updater.download(info, progress=lambda f: self._emit("update_progress", f))
        except Exception as e:
            return {"error": f"Download failed: {e}"}
        updater.launch_installer(path)
        if sys.platform == "win32":
            threading.Timer(0.8, self.quit).start()
            return {"message": "Installing… the app will reopen by itself."}
        return {"message": "Drag the new app into Applications (replace the old one), then reopen it."}

    def quit(self):
        self.review_close()
        if self._window:
            self._window.destroy()

    # ================================================================== fields & filename
    def fields_info(self):
        prefs = settings.load()
        fields = fieldmod.load()
        sep = prefs.get("separator") or fieldmod.DEFAULT_SEPARATOR
        cols = prefs.get("excel_columns") or {}
        return {
            "fields": [{"key": f.key, "label": f.label, "type": f.type, "type_label": TYPE_LABELS[f.type],
                        "instructions": f.instructions, "enabled": f.enabled, "in_filename": f.in_filename,
                        "in_excel": f.in_excel, "builtin": f.builtin} for f in fields],
            "separator": sep, "default_separator": fieldmod.DEFAULT_SEPARATOR,
            "original": bool(prefs.get("filename_original")),
            "file_columns": [{"key": k, "label": label, "on": bool(cols.get(k))} for k, label in FILE_COLUMNS],
            "example": _filename_example(fields, prefs.get("filename_original"), sep),
        }

    def set_separator(self, sep):
        problem = fieldmod.separator_problem(sep)
        if problem:
            return {"problem": problem}
        settings.save(separator=sep)
        return self.fields_info()

    def set_original(self, value):
        fields = fieldmod.load()
        if not fieldmod.filename_keys(fields, value):
            value = True  # the filename needs at least one part
        settings.save(filename_original=bool(value))
        return self.fields_info()

    def set_excel_column(self, key, value):
        cols = dict(settings.load().get("excel_columns") or {})
        cols[key] = bool(value)
        settings.save(excel_columns=cols)
        return self.fields_info()

    def field_set(self, key, attr, value):
        if attr not in ("enabled", "in_filename", "in_excel"):
            return self.fields_info()
        fields = fieldmod.load()
        f = next(x for x in fields if x.key == key)
        setattr(f, attr, bool(value))
        if attr == "enabled" and not value:
            f.in_filename = False
        if attr in ("in_filename", "enabled") and not fieldmod.filename_keys(fields, settings.load().get("filename_original")):
            f.in_filename = True
            f.enabled = True
        fieldmod.save(fields)
        return self.fields_info()

    def field_move(self, key, d):
        fields = fieldmod.load()
        i = next(n for n, x in enumerate(fields) if x.key == key)
        j = i + d
        if 0 <= j < len(fields):
            fields[i], fields[j] = fields[j], fields[i]
            fieldmod.save(fields)
        return self.fields_info()

    def field_save(self, key, label, type_, instructions):
        label, instructions = (label or "").strip(), (instructions or "").strip()
        if not label or not instructions:
            return {"problem": "Please fill in the name and what should be read."}
        fields = fieldmod.load()
        if key:
            f = next(x for x in fields if x.key == key)
            f.label, f.instructions = label, instructions
            if not f.builtin and type_ in TYPE_LABELS:
                f.type = type_
        else:
            fields.append(fieldmod.FieldDef(fieldmod.make_key(label, {x.key for x in fields}), label, instructions,
                                            type_ if type_ in TYPE_LABELS else "text", enabled=True,
                                            in_filename=False, in_excel=True, builtin=False))
        fieldmod.save(fields)
        return self.fields_info()

    def field_delete(self, key):
        fields = [f for f in fieldmod.load() if f.key != key or f.builtin]
        fieldmod.save(fields)
        return self.fields_info()

    # ================================================================== feedback
    def feedback_folder(self, path):
        if not path or not os.path.isdir(path):
            return None
        from src.services import feedback
        n, size = feedback.folder_size(path)
        return {"name": os.path.basename(path), "files": n, "mb": round(size / 1e6, 1)}

    def feedback_send(self, kind, message, screenshot, folder, include_files, screen):
        """screenshot: PNG data URL or None. Returns {"ok": True} | {"saved": path} | {"error": msg}."""
        from PIL import Image
        from src.services import feedback
        message = (message or "").strip()
        if not message:
            return {"error": "Please write a few words about it first."}
        try:
            img = None
            if screenshot:
                img = Image.open(io.BytesIO(base64.b64decode(screenshot.split(",", 1)[1])))
            self._emit("feedback_status", "Preparing…")
            data, meta = feedback.build_package(kind or "feedback", message, img,
                                                folder if folder and os.path.isdir(folder) else None,
                                                include_files=bool(include_files), screen_name=screen or "")
        except Exception as e:
            return {"error": f"Couldn't prepare the feedback: {e}"}
        try:
            self._emit("feedback_status", f"Sending {len(data) / 1e6:.1f} MB…")
            feedback.send(data, meta)
            return {"ok": True}
        except Exception:
            try:
                return {"saved": feedback.save_to_desktop(data)}
            except Exception as e:
                return {"error": f"Couldn't send or save it: {e}"}

    def choose_image(self):
        chosen = _first(self._window.create_file_dialog(
            webview.FileDialog.OPEN, file_types=("Images (*.png;*.jpg;*.jpeg)", "All files (*.*)")))
        if not chosen:
            return None
        from PIL import Image
        img = Image.open(chosen).convert("RGB")
        img.thumbnail((2400, 2400))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    # ================================================================== e-Fatura
    def efatura_import(self, path):
        chosen = self._window.create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=True,
            file_types=("e-Fatura export (*.csv;*.txt)", "All files (*.*)"))
        if not chosen:
            return None
        paths = list(chosen) if isinstance(chosen, (list, tuple)) else [chosen]
        try:
            n, total = efatura.import_files(path, paths)
        except ValueError as e:
            return {"error": str(e)}
        return {"message": f"Read {n} invoice{'s' if n != 1 else ''} from {len(paths)} file"
                           f"{'s' if len(paths) != 1 else ''}. This client now has {total} e-Fatura invoices "
                           "(duplicates are ignored)."}

    def efatura_view(self, path, start=None, end=None):
        """Every case for the period, with its status, the receipt/e-Fatura values and what was decided."""
        stored = efatura.stored_count(path)
        if not stored:
            return {"stored": 0, "items": []}
        result = efatura.compare(path, start, end)
        done = efatura.resolutions(path)
        items = []

        def receipt(inv):
            v = inv["values"]
            return {"supplier": v.get("supplier") or "", "nif": v.get("_nif") or v.get("supplier_nif") or "",
                    "number": v.get("invoice_number") or "", "date": str(v.get("date") or "")[:10],
                    "total": v.get("total_value"), "file": inv["file_name"],
                    "path": os.path.join(inv["folder"] or "", inv["file_name"] or ""), "hash": inv["hash"],
                    "status": inv["status"]}

        def ef_row(r):
            return {"supplier": r["supplier_name"], "nif": r["supplier_nif"], "number": r["number"],
                    "date": r["date"], "total": r["total"], "status": r.get("status") or "",
                    "type": r.get("type") or "", "atcud": r.get("atcud") or ""}

        for inv, r, how in result["matched"]:
            items.append({"id": efatura.invoice_key(inv), "kind": "matched", "how": how,
                          "receipt": receipt(inv), "ef": ef_row(r), "resolution": "matched"})
        for inv, r, diffs in result["differ"]:
            key = efatura.invoice_key(inv)
            items.append({"id": key, "kind": "differ", "diffs": diffs, "receipt": receipt(inv), "ef": ef_row(r),
                          "resolution": done.get(key)})
        for r in result["missing"]:
            key = efatura.row_key(r)
            items.append({"id": key, "kind": "missing", "receipt": None, "ef": ef_row(r), "resolution": done.get(key)})
        for inv in result["not_in_ef"]:
            key = efatura.invoice_key(inv)
            items.append({"id": key, "kind": "not_in_ef", "receipt": receipt(inv), "ef": None,
                          "resolution": done.get(key)})
        order = {"differ": 0, "missing": 1, "not_in_ef": 2, "matched": 3}
        items.sort(key=lambda i: (order[i["kind"]], (i["ef"] or i["receipt"])["date"] or ""))
        self._ef_cache[path] = {i["id"]: i for i in items}
        return {"stored": stored, "items": items, "count_ef": len(efatura.rows(path, start, end))}

    def efatura_resolve(self, path, item_id, resolution):
        efatura.resolve(path, item_id, resolution)
        return True

    def efatura_thumb(self, file_path):
        return self._preview(file_path, width=300, first_page_only=True)

    def efatura_use_values(self, path, item_id):
        """'Use e-Fatura values': the receipt takes the AT's date and total (and is renamed to match)."""
        from src.services.file_manager import FileManager
        item = self._ef_cache.get(path, {}).get(item_id)
        if not item or not item.get("receipt"):
            return {"error": "This case changed; please reload."}
        h = item["receipt"]["hash"]
        known = history.get(h)
        if not known:
            return {"error": "This receipt isn't in the history any more."}
        values = dict(known["values"])
        values["date"], values["total_value"] = item["ef"]["date"], float(item["ef"]["total"])
        current = os.path.join(known["folder"] or "", known["file_name"] or "")
        history.save(h, values, "confirmed", current, project=path)  # never downgrades "renamed"
        if known["status"] == "renamed" and os.path.exists(current):
            prefs = settings.load()
            fields = [f for f in fieldmod.load() if f.enabled]
            keys = fieldmod.filename_keys(fields, prefs.get("filename_original"))
            original = known.get("original_name") or known["file_name"]
            new_name = fieldmod.build_filename(values, original, fields, keys,
                                               prefs.get("separator") or fieldmod.DEFAULT_SEPARATOR)
            if new_name and new_name != known["file_name"]:
                new_path = FileManager.rename_invoice(current, known["folder"], new_name, True)
                if new_path:
                    history.moved(h, new_path)
        return {"ok": True}

    def efatura_find_receipt(self, path, item_id):
        """Copies a chosen receipt into the client's folder and reads it (it then matches by itself)."""
        chosen = _first(self._window.create_file_dialog(
            webview.FileDialog.OPEN, file_types=("Invoices (*.pdf;*.png;*.jpg;*.jpeg;*.webp)", "All files (*.*)")))
        if not chosen:
            return None
        key = key_store.get_api_key()
        if not key:
            return {"error": "Add your Gemini API key in Settings first."}
        target = os.path.join(path, os.path.basename(chosen))
        if os.path.abspath(chosen) != os.path.abspath(target):
            base, ext = os.path.splitext(target)
            n = 2
            while os.path.exists(target):
                target, n = f"{base} ({n}){ext}", n + 1
            shutil.copy2(chosen, target)
        done = threading.Event()
        session = ReviewSession(key, path, on_change=lambda _p: done.set(), only=[os.path.basename(target)])
        done.wait(timeout=120)
        session.close()
        return {"ok": True, "file": os.path.basename(target)}

    def efatura_export(self, path, start=None, end=None, short=""):
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        view = self.efatura_view(path, start, end)
        if not view["items"]:
            return None
        name = f"e-Fatura {os.path.basename(path)}" + (f" – {short}" if short else "")
        out = self._ask_save(path, f"{name}.xlsx")
        if not out:
            return None
        sheets = [("differ", "Values differ"), ("missing", "In e-Fatura, no receipt"),
                  ("not_in_ef", "Receipt not in e-Fatura"), ("matched", "Matched")]
        wb = Workbook()
        wb.remove(wb.active)
        for kind, title in sheets:
            ws = wb.create_sheet(title[:31])
            ws.append(["Date", "Supplier", "NIF", "Document", "Total (receipt)", "Total (e-Fatura)", "File",
                       "Note", "Decision"])
            for cell in ws[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill(start_color="204E27", end_color="204E27", fill_type="solid")
            for i in (x for x in view["items"] if x["kind"] == kind):
                rc, ef = i["receipt"] or {}, i["ef"] or {}
                note = "; ".join(i.get("diffs") or []) or ("probable (same supplier, date and total)"
                                                           if i.get("how") == "probable" else "")
                ws.append([ef.get("date") or rc.get("date"), ef.get("supplier") or rc.get("supplier"),
                           ef.get("nif") or rc.get("nif"), ef.get("number") or rc.get("number"),
                           rc.get("total"), ef.get("total"), rc.get("file") or "", note,
                           {"not_needed": "Not needed", "kept": "Kept receipt values", "registered": "Registered",
                            "matched": ""}.get(i["resolution"] or "", "")])
            for col, w in zip("ABCDEFGHI", (12, 34, 12, 30, 14, 14, 36, 40, 18)):
                ws.column_dimensions[col].width = w
        wb.save(out)
        return True
