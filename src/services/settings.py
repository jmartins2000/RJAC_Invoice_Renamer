"""Small JSON settings file in the user's app-data folder (remembers choices and usage)."""
import datetime
import json
import os
import sys
import threading

APP_DIR_NAME = "RJAC Invoice Renamer"
_lock = threading.Lock()

DEFAULTS = {
    "fields": None,             # list of field definitions (see services/fields.py); None = defaults
    "separator": " ~ ",
    "filename_original": False,  # append the original filename
    "excel_columns": {"original_name": True, "file_name": True, "folder": False},  # file info in the Excel
    "delete_original": True,
    "appearance": "system",      # system | light | dark
    "language": "pt",            # pt (Portugal) | en
    "column_widths": {},         # client table: column key -> width in px (set by dragging)
    "last_source": None,
    "model": None,  # None = the catalog's default
    "usage": {},  # "YYYY-MM": {"invoices": int, "cost_usd": float}
}


def _dir():
    if os.environ.get("RJAC_DATA_DIR"):  # used by tests
        os.makedirs(os.environ["RJAC_DATA_DIR"], exist_ok=True)
        return os.environ["RJAC_DATA_DIR"]
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    path = os.path.join(base, APP_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def _path():
    return os.path.join(_dir(), "settings.json")


def load():
    data = json.loads(json.dumps(DEFAULTS))
    try:
        with open(_path(), encoding="utf-8") as f:
            stored = json.load(f)
        data.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return data


def save(**changes):
    with _lock:
        data = load()
        data.update(changes)
        tmp = _path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, _path())


def add_usage(invoices, cost_usd):
    month = datetime.date.today().strftime("%Y-%m")
    usage = load()["usage"]
    cur = usage.get(month, {"invoices": 0, "cost_usd": 0.0})
    cur["invoices"] += invoices
    cur["cost_usd"] = round(cur["cost_usd"] + cost_usd, 6)
    usage[month] = cur
    save(usage=usage)


def month_usage():
    return load()["usage"].get(datetime.date.today().strftime("%Y-%m"), {"invoices": 0, "cost_usd": 0.0})
