"""The bridge between the HTML screens and the app's Python logic.

Every public method here can be called from JavaScript as `await api.name(...)` (pywebview runs
each call in its own thread) and returns plain JSON-able data. Python pushes live updates to the
page with `_emit(event, data)` → a "py" DOM event. The services (history, Gemini, QR, e-Fatura…)
are UI-independent.
"""
import base64
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading

import webview

from src.services import api_key as key_store
from src.services import efatura, history, i18n, models, periods, qr_at, settings, updater, workbook
from src.services import fields as fieldmod
from src.services.excel_exporter import FILE_COLUMNS, ExcelExporter
from src.services.gemini_service import friendly_error as gemini_friendly
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

    def _ask_save(self, folder, name, file_types=("Excel (*.xlsx)",)):
        return _first(self._window.create_file_dialog(
            webview.FileDialog.SAVE, directory=folder if folder and os.path.isdir(folder) else "",
            save_filename=name, file_types=file_types))

    # ================================================================== app
    def app_info(self):
        prefs = settings.load()
        return {"version": __version__, "has_key": bool(key_store.get_api_key()), "language": i18n.lang(),
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

    def set_column_width(self, key, width):
        """Client table: a column's width in px (None = back to automatic). Same for every client."""
        widths = dict(settings.load().get("column_widths") or {})
        if width:
            widths[str(key)] = max(50, min(900, int(width)))
        else:
            widths.pop(str(key), None)
        settings.save(column_widths=widths)
        return widths

    def set_language(self, lang):
        settings.save(language=lang if lang in i18n.LANGUAGES else "pt")
        return True

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

    def log_ui(self, message):
        """The page reports popups and errors here, so they show in the terminal / logs."""
        print(f"[ui] {str(message)[:2000]}", flush=True)
        return True

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
            return i18n.tr("Paste your key in the box above.")
        err = validate_api_key(key)
        if err:
            return i18n.tr("That key didn't work: {err}", err=err)
        try:
            key_store.save_api_key(key)
        except Exception as e:
            return i18n.tr("Couldn't save the key on this computer: {e}", e=e)
        return None

    # ================================================================== clients (folders)
    def projects(self):
        import time
        t0 = time.time()
        out = []
        for p in history.projects():
            out.append({
                "path": p["path"], "name": p.get("name") or os.path.basename(p["path"]) or p["path"],
                "parent": nice_path(p["path"]),
                "exists": os.path.isdir(p["path"]), "invoices": p["invoices"], "total": round(p["total"], 2),
                "runs": p["runs"], "last_run": (p["last_run"] or "")[:10], "to_check": p["to_check"],
            })
        if time.time() - t0 > 2:
            print(f"[slow] projects() took {time.time() - t0:.1f}s", flush=True)
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

    def _client_name(self, path):
        p = history.project(path) or {}
        return p.get("name") or os.path.basename(path) or path

    def choose_folder(self, start=None):
        chosen = self._ask_folder(start)
        return os.path.abspath(chosen) if chosen else None

    def create_client(self, name, nif, folder, dest=None):
        """New client: name, optional NIF, the folder its receipts arrive in, where renamed copies go."""
        if not folder or not os.path.isdir(folder):
            return {"error": i18n.tr("Choose the folder where this client's receipts are.")}
        path = os.path.abspath(folder)
        existing = history.project(path)
        if existing:
            return {"error": i18n.tr("That folder is already the client \"{name}\".",
                                     name=existing.get('name') or os.path.basename(path))}
        history.add_project(path)
        history.set_details(path, name, nif)
        if dest:
            history.set_destination(path, dest)
        return {"path": path}

    def change_client_folder(self, path):
        """The client's receipts are now in another folder (records move along; files don't)."""
        new = self._ask_folder(os.path.dirname(path))
        if not new:
            return None
        new = os.path.abspath(new)
        if new == os.path.abspath(path):
            return None
        try:
            history.move_project(path, new)
            efatura.move_project(path, new)
        except ValueError as e:
            return {"error": str(e)}
        self._ef_cache.pop(path, None)
        return {"path": new}

    def rename_client(self, path, name, nif=""):
        history.add_project(path)
        history.set_details(path, name, nif)
        return self.folder(path)

    def delete_client(self, path):
        """Deletes the client and everything the app keeps about it. Files on disk are never touched."""
        efatura.delete_project(path)
        history.delete_project(path)
        self._ef_cache.pop(path, None)
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
            "path": path, "name": project.get("name") or os.path.basename(path) or path,
            "folder_name": os.path.basename(path) or path, "custom_name": bool(project.get("name")),
            "nif": project.get("nif") or "", "where": nice_path(path, 4),
            "exists": os.path.isdir(path),
            "periods": [{"label": p[0], "start": p[1][0], "end": p[1][1], "short": p[2], "kind": p[3]}
                        for p in periods.options(history.years(path))],
            "custom": periods.custom_label(),
            "columns": [{"key": f.key, "label": i18n.tr(f.label), "type": f.type} for f in fields if f.in_excel][:5],
            "runs": [{"date": (r["started_at"] or "")[:10], "reads": r["gemini_reads"] or 0,
                      "eur": round((r["cost_usd"] or 0) * self._eur, 2), "renamed": r["renamed"] or 0}
                     for r in runs],
            "example": _filename_example(fields, prefs.get("filename_original"), sep),
            "dest": dest, "dest_label": dest or i18n.tr("This folder (renamed in place)"),
            "column_widths": prefs.get("column_widths") or {},
            "efatura": efatura.stored_count(path),
        }

    def folder_rows(self, path, start=None, end=None):
        fields = [f for f in fieldmod.load() if f.enabled]
        rows = history.query(start, end, path)
        out = []
        for r in rows:
            cells = {f.key: fieldmod.display_value(f, r["values"].get(f.key)) for f in fields}
            out.append({"cells": cells, "file": r["file_name"], "path": os.path.join(r["folder"] or "", r["file_name"] or ""),
                        "status": r["status"], "status_label": i18n.tr(STATUS.get(r["status"], r["status"])),
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
        return {"label": f"{periods.nice(a)} – {periods.nice(b)}", "start": a, "end": b,
                "short": i18n.tr("{a} to {b}", a=a, b=b), "kind": "range"}

    def read_button(self, path):
        """Label for the folder's main button: read N new files (with an estimated cost) or review."""
        if not os.path.isdir(path):
            return {"label": i18n.tr("Folder not found"), "enabled": False, "new": 0}
        files = history.new_pdfs(path)
        n = len(files)
        if not n:
            return {"label": i18n.tr("Review & rename"), "enabled": True, "new": 0, "files": []}
        mid = settings.load().get("model") or models.default_model()
        cost = history.recent_cost_per_read() or models.cost_per_invoice(mid)
        label = i18n.tr("Read 1 new file") if n == 1 else i18n.tr("Read {n} new files", n=n)
        if cost:
            label += f" · ~€{i18n.money(max(0.01, n * cost * self._eur))}"
        return {"label": label, "enabled": True, "new": n, "files": sorted(files)[:300], "cost": label.split(" · ")[-1] if cost else ""}

    def change_dest(self, path):
        project = history.project(path) or {}
        folder = self._ask_folder(project.get("dest_folder") or path)
        if not folder:
            return None
        history.set_destination(path, folder)
        dest = None if os.path.abspath(folder) == os.path.abspath(path) else folder
        return {"dest": dest, "dest_label": dest or i18n.tr("This folder (renamed in place)")}

    def export_folder(self, path, start=None, end=None, short=""):
        rows = history.query(start, end, path)
        if not rows:
            return None
        project = history.project(path) or {}
        name = self._client_name(path) + (f" – {short}" if short else "")
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
        return {"name": self._client_name(path), "folder": path, "dest": session.dest,
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
                "folder": s.folder, "folder_name": self._client_name(s.folder),
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
                "usage": i18n.tr("This month: €{cost} · {n} invoices", cost=i18n.money(u['cost_usd'] * self._eur), n=u['invoices']),
                "fields": i18n.tr("Reading: {fields} · separator \"{sep}\"", fields=", ".join(i18n.tr(x) for x in on),
                                  sep=prefs.get('separator') or fieldmod.DEFAULT_SEPARATOR),
                "appearance": prefs.get("appearance") or "system"}

    def _model_dict(self, info):
        per100 = (i18n.tr("€{cost} per 100 invoices", cost=i18n.money(info.cost * 100 * self._eur))
                  if info.cost is not None else i18n.tr("price unknown"))
        bits = [i18n.tr("Tested on sample invoices: {score} fully correct", score=info.tested) if info.tested
                else i18n.tr("Not tested yet")]
        if info.later:
            cost, when = info.later
            bits.append(i18n.tr("rises to €{cost} per 100 on {date}", cost=i18n.money(cost * 100 * self._eur),
                                date=periods.nice(when.isoformat())))
        if info.note:
            bits.append(i18n.tr(info.note))
        return {"id": info.id, "label": info.label, "tag": i18n.tr(info.tag) if info.tag else "", "price": per100,
                "detail": " · ".join(bits)}

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
        return {"version": i.version, "notes": i.notes or i18n.tr("Improvements and fixes."),
                "direct": bool(i.asset_url)} if i else None

    def releases(self):
        """Published versions this computer can install (for going back to an earlier one)."""
        from packaging.version import Version
        self._releases = {i.version: i for i in updater.list_releases()}
        return [{"version": i.version, "date": i.date, "current": i.version == __version__,
                 "newer": Version(i.version) > Version(__version__),
                 "notes": next((ln.strip(" -*#") for ln in (i.notes or "").splitlines()
                                if ln.strip() and "full changelog" not in ln.lower()), "")[:140]}
                for i in self._releases.values()]

    def install_version(self, version):
        """Installs a specific published version (older or newer). Same flow as an update."""
        info = getattr(self, "_releases", {}).get(version)
        if not info:
            return {"error": i18n.tr("That version isn't available any more.")}
        self._update = info
        return self.update_install()

    def update_install(self):
        """Downloads (progress events) and starts the installer. Returns what to tell the user."""
        info = self._update
        if not info:
            return {"error": i18n.tr("No update found.")}
        if not info.asset_url:
            self.open_url(info.page_url)
            return {"message": i18n.tr("The download page was opened in your browser.")}
        try:
            path = updater.download(info, progress=lambda f: self._emit("update_progress", f))
        except Exception as e:
            return {"error": i18n.tr("Download failed: {e}", e=e)}
        updater.launch_installer(path)
        if sys.platform == "win32":
            threading.Timer(0.8, self.quit).start()
            return {"message": i18n.tr("Installing… the app will reopen by itself.")}
        return {"message": i18n.tr("Drag the new app into Applications (replace the old one), then reopen it.")}

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
            "fields": [{"key": f.key, "label": i18n.tr(f.label), "type": f.type, "type_label": i18n.tr(TYPE_LABELS[f.type]),
                        "instructions": f.instructions, "enabled": f.enabled, "in_filename": f.in_filename,
                        "in_excel": f.in_excel, "builtin": f.builtin} for f in fields],
            "separator": sep, "default_separator": fieldmod.DEFAULT_SEPARATOR,
            "original": bool(prefs.get("filename_original")),
            "file_columns": [{"key": k, "label": i18n.tr(label), "on": bool(cols.get(k))} for k, label in FILE_COLUMNS],
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
            return {"problem": i18n.tr("Please fill in the name and what should be read.")}
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
        return {"name": os.path.basename(path), "files": n, "mb": round(size / 1e6, 1),
                "efatura": efatura.stored_count(path) > 0}

    def feedback_send(self, kind, message, screenshot, folder, include_files, screen):
        """screenshot: PNG data URL or None. Returns {"ok": True} | {"saved": path} | {"error": msg}."""
        from PIL import Image
        from src.services import feedback
        message = (message or "").strip()
        if not message:
            return {"error": i18n.tr("Please write a few words about it first.")}
        try:
            img = None
            if screenshot:
                img = Image.open(io.BytesIO(base64.b64decode(screenshot.split(",", 1)[1])))
            self._emit("feedback_status", "Preparing…")
            data, meta = feedback.build_package(kind or "feedback", message, img,
                                                folder if folder and os.path.isdir(folder) else None,
                                                include_files=bool(include_files), screen_name=screen or "")
        except Exception as e:
            return {"error": i18n.tr("Couldn't prepare the feedback: {e}", e=e)}
        try:
            self._emit("feedback_status", i18n.tr("Sending {mb} MB…", mb=f"{len(data) / 1e6:.1f}".replace(".", "," if i18n.lang() == "pt" else ".")))
            feedback.send(data, meta)
            return {"ok": True}
        except Exception:
            try:
                return {"saved": feedback.save_to_desktop(data)}
            except Exception as e:
                return {"error": i18n.tr("Couldn't send or save it: {e}", e=e)}

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
            file_types=("Exported files (*.csv;*.txt)", "All files (*.*)"))  # labels: letters and spaces only
        if not chosen:
            return None
        paths = list(chosen) if isinstance(chosen, (list, tuple)) else [chosen]
        try:
            n, total = efatura.import_files(path, paths)
        except ValueError as e:
            return {"error": str(e)}
        return {"message": i18n.tr("Read {n} invoices from {f} file(s). This client now has {total} e-Fatura invoices "
                                   "(duplicates are ignored).", n=n, f=len(paths), total=total)}

    def efatura_view(self, path, start=None, end=None):
        """Every case for the period, with its status, the receipt/e-Fatura values, what was decided and
        the status code of each e-Fatura document (matched ones are 1 · DOC. OK unless changed)."""
        stored = efatura.stored_count(path)
        if not stored:
            return {"stored": 0, "items": [], "codes": workbook.codes_for(path), "workbook": self._wb_info(path)}
        result = efatura.compare(path, start, end)
        done = efatura.resolutions(path)
        chosen = efatura.codes(path)
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
                    "type": r.get("type") or "", "atcud": r.get("atcud") or "", "sector": r.get("sector") or "",
                    "vat": r.get("vat"), "base": r.get("base"), "credit_note": bool(r.get("credit_note"))}

        def add(item, r, auto=None):
            if r is not None:
                item["ef_key"] = efatura.row_key(r)
                code = chosen.get(item["ef_key"])
                item["code"], item["code_auto"] = (code, False) if code else (auto, auto is not None)
            else:
                item["ef_key"], item["code"], item["code_auto"] = None, None, False
            items.append(item)

        for inv, r, how in result["matched"]:
            add({"id": efatura.invoice_key(inv), "kind": "matched", "how": how,
                 "receipt": receipt(inv), "ef": ef_row(r), "resolution": "matched"}, r, auto=1)
        for inv, r, diffs in result["differ"]:
            key = efatura.invoice_key(inv)
            add({"id": key, "kind": "differ", "diffs": diffs, "receipt": receipt(inv), "ef": ef_row(r),
                 "resolution": done.get(key)}, r, auto=1 if done.get(key) else None)
        for r in result["missing"]:
            key = efatura.row_key(r)
            add({"id": key, "kind": "missing", "receipt": None, "ef": ef_row(r), "resolution": done.get(key)}, r)
        for r in result["cancelled"]:
            key = efatura.row_key(r)
            add({"id": key, "kind": "cancelled", "receipt": None, "ef": ef_row(r), "resolution": "cancelled"}, r)
        for inv in result["not_in_ef"]:
            key = efatura.invoice_key(inv)
            add({"id": key, "kind": "not_in_ef", "receipt": receipt(inv), "ef": None,
                 "resolution": done.get(key)}, None)
        order = {"differ": 0, "missing": 1, "not_in_ef": 2, "matched": 3, "cancelled": 4}
        items.sort(key=lambda i: (order[i["kind"]], (i["ef"] or i["receipt"])["date"] or ""))
        self._ef_cache[path] = {i["id"]: i for i in items}
        return {"stored": stored, "items": items, "codes": workbook.codes_for(path), "workbook": self._wb_info(path),
                "count_ef": len(efatura.rows(path, start, end))}

    def _wb_info(self, path):
        w = workbook.info(path)
        return {"name": w["name"], "imported": w["imported_at"][:10]} if w else None

    def efatura_import_workbook(self, path, again=False):
        """Opens the client's "Conferência EF" workbook. If every sheet with documents is recognised it's
        imported straight away ({"imported": ...}); otherwise the sheets come back for mapping by hand
        ({"mapping": ...}). again=True reopens the last file for mapping (to adjust how it was read)."""
        if again and getattr(self, "_wb_pending", None):
            chosen = self._wb_pending
        else:
            chosen = _first(self._window.create_file_dialog(
                webview.FileDialog.OPEN, file_types=("Excel workbooks (*.xlsx;*.xlsm)", "All files (*.*)")))
        if not chosen:
            return None
        self._wb_pending = chosen
        say = self._wb_say
        say(i18n.tr("Opening {file}…", file=os.path.basename(chosen)), 0.02, start=True)
        try:
            sheets = workbook.preview(chosen, path)
        except Exception as e:  # damaged / not an Excel file
            return {"error": i18n.tr("Couldn't read that workbook: {e}", e=e)}
        unknown = [s for s in sheets if s["looks_like_data"] and not s["layout"]]
        if not unknown and not again and any(s["layout"] for s in sheets):
            return {"imported": self._wb_import(path, chosen)}
        agent = None
        key = key_store.get_api_key()
        if unknown and key:  # ask Gemini to work out the layout; shown as a suggestion to confirm
            try:
                from src.services import layout_agent
                say(i18n.tr("Some sheets have a layout the app doesn't know: asking Gemini to work it out…"), 0.08)
                res = layout_agent.propose(key, chosen, progress=say)
                for sh in unknown:
                    if sh["sheet"] in res["layouts"]:
                        sh["layout"] = {**res["layouts"][sh["sheet"]], "suggested": True}
                    elif sh["sheet"] in res["skip"]:
                        sh["suggested_skip"] = True
                agent = {"cost_eur": round(res["cost_usd"] * self._eur, 3),
                         "found": sum(1 for sh in unknown if sh["layout"] or sh.get("suggested_skip"))}
            except Exception as e:
                print(f"Layout agent failed: {e}")
                agent = {"error": gemini_friendly(e)}
        return {"mapping": {"file": os.path.basename(chosen), "sheets": sheets, "agent": agent,
                            "fields": [{"key": k, "label": v} for k, v in workbook.FIELDS]}}

    def _wb_say(self, text, fraction=None, start=False):
        """A step of a workbook import, shown in the progress window (and printed to the log)."""
        print(f"[workbook] {text}", flush=True)
        self._emit("wb_progress", {"text": text, "fraction": fraction, "start": start})

    def efatura_workbook_try(self, sheet, layout):
        """What a mapping would import from one sheet (live check in the mapping screen)."""
        try:
            return workbook.try_layout(self._wb_pending, sheet, layout)
        except Exception as e:
            return {"documents": 0, "coded": 0, "total": 0, "examples": [], "error": str(e)}

    def efatura_workbook_confirm(self, path, layouts, skip):
        """Imports the pending workbook with the sheets mapped by hand (remembered for this client)."""
        try:
            return {"imported": self._wb_import(path, self._wb_pending, layouts, skip)}
        except ValueError as e:
            return {"error": str(e)}

    def _wb_import(self, path, file, layouts=None, skip=()):
        say = self._wb_say
        data = workbook.read(file, overrides=layouts or {}, saved=workbook.saved_layouts(path), skip=set(skip),
                             progress=say)
        r = workbook.import_workbook(path, file, data=data, progress=say)
        say(i18n.tr("Done: {n} documents.", n=f"{r['documents']:,}".replace(",", ".") if i18n.lang() == "pt" else f"{r['documents']:,}"), 1.0)
        project = history.project(path) or {}
        r["offer_details"] = bool((r["client_name"] and not project.get("name"))
                                  or (r["client_nif"] and not project.get("nif")))
        r["file"] = os.path.basename(file)
        return r

    def efatura_export_workbook(self, path):
        """The client's workbook with everything in the app written in (saved as a new file)."""
        w = workbook.info(path)
        if not w:
            return {"error": i18n.tr("Import the client's workbook first.")}
        base, ext = os.path.splitext(w["name"])
        base = re.sub(r"\s*\(atualizado [^)]*\)$", "", base)
        name = f"{base} (atualizado {datetime.date.today().isoformat()}){ext}"
        types = ("Excel with macros (*.xlsm)",) if ext.lower() == ".xlsm" else ("Excel (*.xlsx)",)
        out = self._ask_save(os.path.dirname(w["original"]), name, types)
        if not out:
            return None
        if os.path.abspath(out) == os.path.abspath(w["original"]):
            return {"error": i18n.tr("Save it under a new name: the original workbook is never overwritten.")}
        try:
            return workbook.export_workbook(path, out)
        except Exception as e:
            return {"error": i18n.tr("Couldn't write the workbook: {e}", e=e)}

    def efatura_set_code(self, path, item_id, code):
        item = self._ef_cache.get(path, {}).get(item_id)
        if not item or not item.get("ef_key"):
            return False
        efatura.set_code(path, item["ef_key"], code)
        return True

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
            return {"error": i18n.tr("This case changed; please reload.")}
        h = item["receipt"]["hash"]
        known = history.get(h)
        if not known:
            return {"error": i18n.tr("This receipt isn't in the history any more.")}
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
            return {"error": i18n.tr("Add your Gemini API key in Settings first.")}
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
        """Excel for the accountant: first sheet in his "Conferência EF" layout (one row per e-Fatura
        document, code in "INSERIR CÓD." and its description, coloured like his workbook), then monthly
        totals, then the cases that need a look."""
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        view = self.efatura_view(path, start, end)
        if not view["items"]:
            return None
        name = f"e-Fatura {self._client_name(path)}" + (f" – {short}" if short else "")
        out = self._ask_save(path, f"{name}.xlsx")
        if not out:
            return None
        head_font = Font(bold=True, color="FFFFFF")
        head_fill = PatternFill(start_color="204E27", end_color="204E27", fill_type="solid")
        client_codes = workbook.codes_for(path)
        by_code = {c["code"]: c for c in client_codes}
        label_of = {c["code"]: c["label"] for c in client_codes}

        def header(ws, cols, widths):
            ws.append(cols)
            for cell in ws[1]:
                cell.font, cell.fill = head_font, head_fill
                cell.alignment = Alignment(wrap_text=True, vertical="center")
            for i, w in enumerate(widths):
                ws.column_dimensions[chr(65 + i)].width = w
            ws.freeze_panes = "A2"

        def as_date(iso):
            try:
                return datetime.date.fromisoformat(iso) if iso else None
            except ValueError:
                return iso

        wb = Workbook()
        ws = wb.active
        ws.title = "Conferência"
        header(ws, ["SETOR", "EMITENTE", "Nº FATURA / ATCUD", "TIPO", "DATA EMISSÃO", "TOTAL", "IVA",
                    "BASE TRIBUTÁVEL", "SITUAÇÃO", "COM. EMITENTE", "INSERIR CÓD.", "DESCRITIVO CHECK", "MÊS",
                    "FICHEIRO"], (22, 44, 34, 18, 13, 12, 11, 13, 20, 10, 9, 30, 6, 40))
        docs = sorted((i for i in view["items"] if i["ef"]), key=lambda i: (i["ef"]["date"] or "", i["ef"]["nif"]))
        for i in docs:
            ef = i["ef"]
            number = f"{ef['number']} / {ef['atcud']}" if ef["atcud"] else ef["number"]
            base = ef["base"] if ef["base"] is not None else (
                round(ef["total"] - ef["vat"], 2) if ef["vat"] is not None else None)
            code = i["code"]
            ws.append([ef["sector"], f"{ef['nif']} - {ef['supplier']}".strip(" -"), number, ef["type"],
                       as_date(ef["date"]), ef["total"], ef["vat"], base, ef["status"], "", code,
                       label_of.get(code, ""), int(ef["date"][5:7]) if ef["date"] else None,
                       (i["receipt"] or {}).get("file") or ""])
            row = ws[ws.max_row]
            row[4].number_format = "yyyy-mm-dd"
            for c in row[5:8]:
                c.number_format = "#,##0.00"
            c = by_code.get(code)
            if c and c["color"]:
                fill = PatternFill(start_color=c["color"], end_color=c["color"], fill_type="solid")
                for cell in row[:13]:
                    cell.fill, cell.font = fill, Font(color=c["text"])
        ws.auto_filter.ref = f"A1:N{ws.max_row}"

        ws = wb.create_sheet("Totais mensais")
        header(ws, ["MÊS", "Nº DOCUMENTOS", "IVA", "TOTAL", "BASE TRIBUTÁVEL"], (10, 15, 14, 14, 17))
        for m in efatura.monthly_totals([efatura_row for efatura_row in efatura.rows(path, start, end)]):
            ws.append([m["month"], m["count"], round(m["vat"], 2), round(m["total"], 2), round(m["base"], 2)])
            for c in ws[ws.max_row][2:5]:
                c.number_format = "#,##0.00"
        ws.append([])
        ws.append(["Notas de crédito a subtrair; documentos anulados pelo emitente não contam."])

        sheets = [("differ", "Valores diferentes"), ("missing", "Sem recibo na pasta"),
                  ("not_in_ef", "Recibo fora do e-Fatura")]
        for kind, title in sheets:
            ws = wb.create_sheet(title[:31])
            header(ws, ["Data", "Fornecedor", "NIF", "Documento", "Total (recibo)", "Total (e-Fatura)",
                        "Ficheiro", "Nota", "Decisão"], (12, 34, 12, 30, 14, 14, 36, 40, 34))
            for i in (x for x in view["items"] if x["kind"] == kind):
                rc, ef = i["receipt"] or {}, i["ef"] or {}
                decision = label_of.get(i["code"]) or {
                    "not_needed": i18n.tr("Not needed"), "kept": i18n.tr("Keep receipt values"), "registered": i18n.tr("Registered")
                }.get(i["resolution"] or "", "")
                ws.append([ef.get("date") or rc.get("date"), ef.get("supplier") or rc.get("supplier"),
                           ef.get("nif") or rc.get("nif"), ef.get("number") or rc.get("number"),
                           rc.get("total"), ef.get("total"), rc.get("file") or "",
                           "; ".join(i.get("diffs") or []), decision])
        wb.save(out)
        return True
