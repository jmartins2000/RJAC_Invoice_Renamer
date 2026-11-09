"""Every invoice the app has read, kept on this computer (SQLite).

Invoices are identified by a fingerprint of the file's contents (SHA-256), so an invoice is
recognised again after it has been renamed or moved, and is never sent to Gemini twice.
"""
import datetime
import hashlib
import json
import os
import sqlite3
import threading

_lock = threading.Lock()
_conn = None


def _db():
    global _conn
    if _conn is None:
        from src.services.settings import _dir
        _conn = sqlite3.connect(os.path.join(_dir(), "history.sqlite3"), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript("""
            CREATE TABLE IF NOT EXISTS invoices (
                hash TEXT PRIMARY KEY,
                values_json TEXT NOT NULL,
                status TEXT NOT NULL,          -- read | confirmed | renamed
                original_name TEXT,
                file_name TEXT,                -- current name (after rename)
                folder TEXT,                   -- current folder
                invoice_date TEXT,             -- copied from values for period filters
                model TEXT,
                processed_at TEXT,
                updated_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_folder ON invoices(folder);
            CREATE INDEX IF NOT EXISTS idx_date ON invoices(invoice_date);
        """)
    return _conn


def fingerprint(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def get(file_hash):
    with _lock:
        row = _db().execute("SELECT * FROM invoices WHERE hash=?", (file_hash,)).fetchone()
    return _row(row) if row else None


def _row(row):
    d = dict(row)
    d["values"] = json.loads(d.pop("values_json"))
    return d


def save(file_hash, values, status, path, model=None, original_name=None):
    """Insert or update. Never downgrades status (renamed > confirmed > read)."""
    rank = {"read": 0, "confirmed": 1, "renamed": 2}
    clean = {k: v for k, v in values.items() if k not in ("error",)}
    with _lock:
        db = _db()
        old = db.execute("SELECT status, original_name, processed_at, model FROM invoices WHERE hash=?",
                         (file_hash,)).fetchone()
        if old and rank.get(old["status"], 0) > rank.get(status, 0):
            status = old["status"]
        db.execute("""INSERT OR REPLACE INTO invoices
            (hash, values_json, status, original_name, file_name, folder, invoice_date, model, processed_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""", (
            file_hash, json.dumps(clean, ensure_ascii=False), status,
            (old["original_name"] if old and old["original_name"] else original_name or os.path.basename(path)),
            os.path.basename(path), os.path.dirname(os.path.abspath(path)),
            str(clean.get("date") or "")[:10],
            model or (old["model"] if old else None),
            old["processed_at"] if old else _now(), _now()))
        db.commit()


def moved(file_hash, new_path):
    with _lock:
        _db().execute("UPDATE invoices SET file_name=?, folder=?, status='renamed', updated_at=? WHERE hash=?",
                      (os.path.basename(new_path), os.path.dirname(os.path.abspath(new_path)), _now(), file_hash))
        _db().commit()


def query(start=None, end=None, folder=None):
    """Invoices, optionally by invoice date range (inclusive, YYYY-MM-DD) and folder."""
    sql, args = "SELECT * FROM invoices WHERE 1=1", []
    if start:
        sql += " AND invoice_date >= ?"; args.append(start)
    if end:
        sql += " AND invoice_date <= ? AND invoice_date != ''"; args.append(end)
    if folder:
        sql += " AND folder = ?"; args.append(folder)
    sql += " ORDER BY invoice_date, file_name"
    with _lock:
        rows = [_row(r) for r in _db().execute(sql, args).fetchall()]
    # Documents with no values (e.g. not invoices) are remembered to avoid re-reading, but not listed.
    return [r for r in rows if any(v not in (None, "") for v in r["values"].values())]


def folders():
    with _lock:
        return [r[0] for r in _db().execute(
            "SELECT folder, COUNT(*) c FROM invoices GROUP BY folder ORDER BY MAX(updated_at) DESC").fetchall()]


def years():
    with _lock:
        return sorted({r[0][:4] for r in _db().execute(
            "SELECT DISTINCT invoice_date FROM invoices WHERE invoice_date != ''").fetchall()}, reverse=True)


def delete(file_hash):
    with _lock:
        _db().execute("DELETE FROM invoices WHERE hash=?", (file_hash,))
        _db().commit()
