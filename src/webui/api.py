"""The bridge between the HTML screens and the app's Python logic.

Every public method here can be called from JavaScript as `await api.name(...)` and returns plain
JSON-able data. The services (history, Gemini, QR, e-Fatura…) are the same as the Tk app's.
"""
import os
import threading

import webview

from src.services import history
from src.version import __version__


class Api:
    def __init__(self):
        self.window = None  # set by the app once the window exists

    # --- app ---
    def app_info(self):
        return {"version": __version__}

    # --- clients (folders) ---
    def projects(self):
        out = []
        for p in history.projects():
            out.append({
                "path": p["path"], "name": os.path.basename(p["path"]) or p["path"],
                "parent": " › ".join([b for b in os.path.dirname(p["path"]).replace("\\", "/").split("/") if b][-3:]),
                "exists": os.path.isdir(p["path"]), "invoices": p["invoices"], "total": round(p["total"], 2),
                "runs": p["runs"], "last_run": (p["last_run"] or "")[:10], "to_check": p["to_check"],
            })
        return out

    def new_files(self, path):
        """Number of files in the folder never read before (reads file contents, so call it lazily)."""
        return len(history.new_pdfs(path)) if os.path.isdir(path) else 0

    def add_folder(self):
        chosen = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        if not chosen:
            return None
        path = os.path.abspath(chosen[0] if isinstance(chosen, (list, tuple)) else chosen)
        history.add_project(path)
        return path
