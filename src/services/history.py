"""Every invoice the app has read, kept on this computer (SQLite).

Invoices are identified by a fingerprint of the file's contents (SHA-256), so an invoice is
recognised again after it has been renamed or moved, and is never sent to Gemini twice.
"""
import datetime
import hashlib
import json
import os
import re
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
            CREATE TABLE IF NOT EXISTS projects (
                path TEXT PRIMARY KEY,         -- the folder the invoices come from
                dest_folder TEXT,              -- where renamed files go (NULL = same folder)
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT,
                started_at TEXT,
                finished_at TEXT,
                files INTEGER DEFAULT 0,       -- PDFs in the folder at the time
                gemini_reads INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0,
                renamed INTEGER DEFAULT 0
            );
        """)
        cols = {r[1] for r in _conn.execute("PRAGMA table_info(invoices)")}
        if "project" not in cols:  # older history: the folder it was read in is its project
            _conn.execute("ALTER TABLE invoices ADD COLUMN project TEXT")
            _conn.execute("UPDATE invoices SET project = folder")
        if "run_id" not in cols:
            _conn.execute("ALTER TABLE invoices ADD COLUMN run_id INTEGER")
        if "hidden" not in {r[1] for r in _conn.execute("PRAGMA table_info(projects)")}:
            _conn.execute("ALTER TABLE projects ADD COLUMN hidden INTEGER DEFAULT 0")
        pcols = {r[1] for r in _conn.execute("PRAGMA table_info(projects)")}
        if "name" not in pcols:  # the client's name as the user calls it (default: folder name)
            _conn.execute("ALTER TABLE projects ADD COLUMN name TEXT")
        if "nif" not in pcols:  # the client's NIF (optional; used in e-Fatura workbooks)
            _conn.execute("ALTER TABLE projects ADD COLUMN nif TEXT")
        _conn.commit()
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


def save(file_hash, values, status, path, model=None, original_name=None, project=None, run_id=None, force=False):
    """Insert or update. Never downgrades status (renamed > confirmed > read).
    `project` is the folder being reviewed: an invoice belongs to the folder it was last reviewed in
    (renaming it into another folder doesn't change that). Without a project, the old one is kept."""
    rank = {"read": 0, "confirmed": 1, "renamed": 2}
    clean = {k: v for k, v in values.items() if k not in ("error",)}
    with _lock:
        db = _db()
        old = db.execute("SELECT status, original_name, processed_at, model, project, run_id FROM invoices "
                         "WHERE hash=?", (file_hash,)).fetchone()
        if old and not force and rank.get(old["status"], 0) > rank.get(status, 0):
            status = old["status"]
        db.execute("""INSERT OR REPLACE INTO invoices
            (hash, values_json, status, original_name, file_name, folder, invoice_date, model, processed_at, updated_at,
             project, run_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
            file_hash, json.dumps(clean, ensure_ascii=False), status,
            (old["original_name"] if old and old["original_name"] else original_name or os.path.basename(path)),
            os.path.basename(path), os.path.dirname(os.path.abspath(path)),
            str(clean.get("date") or "")[:10],
            model or (old["model"] if old else None),
            old["processed_at"] if old else _now(), _now(),
            (os.path.abspath(project) if project else
             old["project"] if old and old["project"] else os.path.dirname(os.path.abspath(path))),
            old["run_id"] if old and old["run_id"] else run_id))
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
        sql += " AND project = ?"; args.append(folder)
    sql += " ORDER BY invoice_date, file_name"
    with _lock:
        rows = [_row(r) for r in _db().execute(sql, args).fetchall()]
    # Documents with no values (e.g. not invoices) are remembered to avoid re-reading, but not listed.
    return [r for r in rows if any(v not in (None, "") for v in r["values"].values())]


def folders():
    """Project folders, most recently used first."""
    return [p["path"] for p in projects()]


# ------------------------------------------------------------------ projects & runs
def add_project(path):
    path = os.path.abspath(path)
    with _lock:
        _db().execute("INSERT OR IGNORE INTO projects (path, created_at) VALUES (?, ?)", (path, _now()))
        _db().execute("UPDATE projects SET hidden=0 WHERE path=?", (path,))
        _db().commit()
    return path


def remove_project(path):
    """Forget a folder (its invoices stay in the history, so nothing is re-read)."""
    with _lock:
        _db().execute("UPDATE projects SET hidden=1 WHERE path=?", (path,))
        _db().commit()


def projects():
    """All project folders with stats, most recently used first."""
    with _lock:
        db = _db()
        db.execute("INSERT OR IGNORE INTO projects (path, created_at) SELECT DISTINCT project, MIN(processed_at) "
                   "FROM invoices WHERE project IS NOT NULL GROUP BY project")
        db.commit()
        rows = db.execute("""
            SELECT p.path, p.dest_folder, p.created_at, p.name, p.nif,
                   (SELECT COUNT(*) FROM runs r WHERE r.project = p.path) AS runs,
                   (SELECT MAX(started_at) FROM runs r WHERE r.project = p.path) AS last_run,
                   COALESCE((SELECT MAX(updated_at) FROM invoices i WHERE i.project = p.path), p.created_at) AS used
            FROM projects p WHERE COALESCE(p.hidden, 0) = 0 ORDER BY used DESC""").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        inv = query(folder=d["path"])
        if not inv and not d["runs"] and not os.path.isdir(d["path"]):
            remove_project(d["path"])  # gone from disk and nothing recorded: drop it
            continue
        d["invoices"] = len(inv)
        d["total"] = sum(i["values"].get("total_value") or 0 for i in inv
                         if isinstance(i["values"].get("total_value"), (int, float)))
        d["to_check"] = sum(1 for i in inv if i["status"] == "read")
        out.append(d)
    return out


def set_details(path, name=None, nif=None):
    """The client's name (empty = use the folder's name) and NIF."""
    with _lock:
        _db().execute("UPDATE projects SET name=?, nif=? WHERE path=?",
                      ((name or "").strip() or None, re.sub(r"\D", "", nif or "") or None, os.path.abspath(path)))
        _db().commit()


def delete_project(path):
    """Deletes a client from the app: its invoices as read, runs and the client itself.
    Never touches files on disk. (e-Fatura data is deleted by efatura.delete_project.)"""
    path = os.path.abspath(path)
    with _lock:
        db = _db()
        db.execute("DELETE FROM invoices WHERE project=?", (path,))
        db.execute("DELETE FROM runs WHERE project=?", (path,))
        db.execute("DELETE FROM projects WHERE path=?", (path,))
        db.commit()


def project(path):
    return next((p for p in projects() if p["path"] == os.path.abspath(path)), None)


def set_destination(path, dest):
    with _lock:
        _db().execute("UPDATE projects SET dest_folder=? WHERE path=?",
                      (None if not dest or os.path.abspath(dest) == os.path.abspath(path) else dest, path))
        _db().commit()


def new_pdfs(path):
    """PDF files in the folder that have never been read (checked by name, then by contents)."""
    try:
        from src.services.file_types import list_invoices
        names = list_invoices(path)
    except OSError:
        return []
    with _lock:
        known = {r[0] for r in _db().execute("SELECT file_name FROM invoices WHERE folder=?",
                                             (os.path.abspath(path),)).fetchall()}
    out = []
    for n in names:
        if n in known:
            continue
        try:
            if get(fingerprint(os.path.join(path, n))) is None:
                out.append(n)
        except OSError:
            pass
    return out


def start_run(path, files):
    with _lock:
        cur = _db().execute("INSERT INTO runs (project, started_at, files) VALUES (?,?,?)",
                            (os.path.abspath(path), _now(), files))
        _db().commit()
        return cur.lastrowid


def finish_run(run_id, gemini_reads=0, cost_usd=0.0, renamed=0):
    """Record what a run did; runs that did nothing are dropped."""
    with _lock:
        db = _db()
        row = db.execute("SELECT gemini_reads, cost_usd, renamed FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return
        g, c, rn = row[0] + gemini_reads, row[1] + cost_usd, row[2] + renamed
        if g == 0 and rn == 0:
            db.execute("DELETE FROM runs WHERE id=?", (run_id,))
        else:
            db.execute("UPDATE runs SET finished_at=?, gemini_reads=?, cost_usd=?, renamed=? WHERE id=?",
                       (_now(), g, c, rn, run_id))
        db.commit()


def runs(path):
    with _lock:
        return [dict(r) for r in _db().execute(
            "SELECT * FROM runs WHERE project=? ORDER BY started_at DESC", (os.path.abspath(path),)).fetchall()]


def years(project=None):
    """Years that have invoices (for one client folder, or all)."""
    sql, args = "SELECT DISTINCT invoice_date FROM invoices WHERE invoice_date != ''", []
    if project:
        sql += " AND project = ?"; args.append(os.path.abspath(project))
    with _lock:
        return sorted({r[0][:4] for r in _db().execute(sql, args).fetchall() if r[0][:4].isdigit()}, reverse=True)


def delete(file_hash):
    with _lock:
        _db().execute("DELETE FROM invoices WHERE hash=?", (file_hash,))
        _db().commit()


def recent_cost_per_read(last_runs=3):
    """Average USD per Gemini read over the most recent runs on this computer, or None."""
    with _lock:
        rows = _db().execute("SELECT cost_usd, gemini_reads FROM runs WHERE gemini_reads > 0 "
                             "ORDER BY started_at DESC LIMIT ?", (last_runs,)).fetchall()
    reads = sum(r[1] for r in rows)
    return (sum(r[0] for r in rows) / reads) if reads >= 5 else None


def supplier_name_for_nif(nif):
    """Most recent supplier name seen for this NIF (from earlier invoices), or None."""
    if not nif:
        return None
    with _lock:
        row = _db().execute(
            "SELECT json_extract(values_json, '$.supplier') FROM invoices "
            "WHERE (json_extract(values_json, '$._nif') = ? OR json_extract(values_json, '$.supplier_nif') = ?) "
            "AND COALESCE(json_extract(values_json, '$.supplier'), '') != '' "
            "ORDER BY updated_at DESC LIMIT 1", (nif, nif)).fetchone()
    return row[0] if row else None
