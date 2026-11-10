"""Packages and sends feedback (message, screenshot, optional folder data) to the owner's inbox.

The inbox is a small Cloudflare Worker (feedback_worker/). The app can only upload; reading needs
the owner's private admin token. Large packages are sent in parts of up to 20 MB.
If sending fails, the package is saved to the Desktop to send another way.
"""
import datetime
import io
import json
import os
import platform
import secrets
import zipfile

import requests

from src.version import __version__

ENDPOINT = os.environ.get("RJAC_FEEDBACK_URL", "https://rjac-feedback.rjac-invoices.workers.dev")
PART = 20 * 1024 * 1024
MAX_TOTAL = 19 * PART


def folder_size(path):
    from src.services.file_types import list_invoices
    files = list_invoices(path)
    return len(files), sum(os.path.getsize(os.path.join(path, f)) for f in files)


def build_package(kind, message, screenshot=None, folder=None, include_files=True, screen_name=""):
    """Returns (zip bytes, metadata dict)."""
    from src.services import history, settings

    prefs = settings.load()
    prefs.pop("usage", None)
    meta = {
        "kind": kind, "message": message, "screen": screen_name,
        "app_version": __version__, "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(), "sent_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "folder": os.path.basename(folder) if folder else None,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("feedback.json", json.dumps(meta, indent=2, ensure_ascii=False))
        z.writestr("message.txt", f"[{kind}]\n\n{message}\n")
        z.writestr("settings.json", json.dumps(prefs, indent=2, ensure_ascii=False))  # never contains the API key
        if screenshot is not None:
            img = io.BytesIO()
            screenshot.save(img, "PNG")
            z.writestr("screenshot.png", img.getvalue())
        if folder:
            z.writestr("folder/history.json", json.dumps(
                {"invoices": history.query(folder=folder), "runs": history.runs(folder),
                 "project": history.project(folder)}, indent=2, ensure_ascii=False, default=str))
            if include_files:
                from src.services.file_types import list_invoices
                for f in list_invoices(folder):
                    z.write(os.path.join(folder, f), f"folder/files/{f}")
            _add_efatura(z, folder)
    data = buf.getvalue()
    meta["bytes"] = len(data)
    return data, meta


def _add_efatura(z, folder):
    """The client's e-Fatura data, if any: original export files, imported rows, comparison, decisions."""
    from src.services import efatura
    try:
        if not efatura.stored_count(folder):
            return
        for p in efatura.kept_exports(folder):
            z.write(p, f"folder/efatura/exports/{os.path.basename(p)}")
        result = efatura.compare(folder)
        slim = lambda inv: {k: inv.get(k) for k in ("hash", "file_name", "status", "values")}  # noqa: E731
        comparison = {
            "matched": [{"receipt": slim(i), "efatura": r, "how": how} for i, r, how in result["matched"]],
            "differ": [{"receipt": slim(i), "efatura": r, "differences": d} for i, r, d in result["differ"]],
            "missing": result["missing"], "not_in_ef": [slim(i) for i in result["not_in_ef"]],
        }
        z.writestr("folder/efatura/rows.json", json.dumps(efatura.rows(folder), indent=1, ensure_ascii=False))
        z.writestr("folder/efatura/comparison.json",
                   json.dumps(comparison, indent=1, ensure_ascii=False, default=str))
        z.writestr("folder/efatura/decisions.json",
                   json.dumps(efatura.resolutions(folder), indent=1, ensure_ascii=False))
    except Exception as e:  # feedback must still go out even if this part fails
        z.writestr("folder/efatura/error.txt", f"Couldn't add the e-Fatura data: {e}")


def send(data, meta, progress=None):
    """Uploads the package. Returns the submission id. Raises on failure."""
    if len(data) > MAX_TOTAL:
        raise ValueError("The package is too large to send (over 380 MB). Untick the folder files and try again.")
    sid = f"{datetime.datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(4)}"
    headers = {"x-rjac-app": __version__}
    chunks = [data[i:i + PART] for i in range(0, len(data), PART)] or [b""]
    for n, chunk in enumerate(chunks):
        r = requests.put(f"{ENDPOINT}/upload/{sid}/{n}", data=chunk, headers=headers, timeout=120)
        r.raise_for_status()
        if progress:
            progress((n + 1) / (len(chunks) + 1))
    r = requests.post(f"{ENDPOINT}/upload/{sid}/done", data=json.dumps({**meta, "parts": len(chunks)}),
                      headers=headers, timeout=60)
    r.raise_for_status()
    if progress:
        progress(1.0)
    return sid


def save_to_desktop(data):
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.isdir(desktop):
        desktop = os.path.expanduser("~")
    path = os.path.join(desktop, f"RJAC feedback {datetime.datetime.now():%Y-%m-%d %H%M}.zip")
    with open(path, "wb") as f:
        f.write(data)
    return path
