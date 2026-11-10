"""Import the e-Fatura export ("Obter dados para Excel") and compare it with a client's invoices.

The export is the list of invoices the AT has for a NIF as buyer (Portal das Finanças → e-Fatura →
Faturação → Adquirente). Its exact column names have varied over time, so columns are detected by
keywords. Known quirks handled here: ';' separator, Windows (cp1252) or UTF-8 encoding, Portuguese
numbers ("1.016,26"), DD-MM-YYYY dates, supplier NIF and name sometimes merged in one column,
document number and ATCUD sometimes merged, credit notes without a minus sign, ~300 rows per file
(so several files can be imported and are de-duplicated).
"""
import csv
import datetime
import io
import json
import os
import re
import unicodedata

from src.services import history

ATCUD = re.compile(r"^[A-Z0-9]{8,}-\d+$", re.I)


def _plain(s):
    """Lowercase, no accents, single spaces — for matching column names."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.lower()).strip()


# (field, test on the plain header). Order matters: first match wins for each column.
COLUMN_RULES = [
    ("supplier_nif", lambda h: "nif" in h and ("emit" in h or "fornec" in h or "comerc" in h)),
    ("supplier_name", lambda h: ("nome" in h or "designa" in h) and ("emit" in h or "fornec" in h or "comerc" in h)),
    ("supplier", lambda h: h in ("emitente", "fornecedor", "comerciante") or h.startswith("emitente")),
    # A column like "Nº Fatura / ATCUD" holds both: treat it as the number (split later)
    ("number", lambda h: "atcud" in h and ("fatura" in h or "/" in h or "doc" in h)),
    ("atcud", lambda h: "atcud" in h or "codigo de controlo" in h or "cod. controlo" in h),
    ("number", lambda h: ("fatura" in h or "documento" in h or h.startswith("n")) and
     ("n." in h or "no" in h.split() or "num" in h or "nº" in h or "n" == h.split()[0] or "/" in h)),
    ("date", lambda h: "data" in h and ("emiss" in h or h == "data")),
    ("type", lambda h: h.startswith("tipo")),
    ("sector", lambda h: "setor" in h or "sector" in h or "atividade" in h),
    ("status", lambda h: "situa" in h or "estado" in h),
    ("base", lambda h: "base" in h or "tributav" in h or "incid" in h),
    ("vat", lambda h: h.startswith("iva") or "valor iva" in h or h == "imposto"),
    ("total", lambda h: "total" in h),
]


def _decode(raw):
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _number(s):
    s = str(s or "").strip().replace("€", "").replace(" ", "").replace(" ", "")
    if not s:
        return None
    neg = s.startswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("-()")
    if "," in s:  # Portuguese: 1.016,26
        s = s.replace(".", "").replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def _date(s):
    s = str(s or "").strip()[:10]
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def norm_number(s):
    """Document number for comparing: no spaces, uppercase, '_' (from filenames) back to '/'."""
    return re.sub(r"\s+", "", str(s or "")).upper().replace("_", "/")


def _map_columns(header):
    mapping, used = {}, set()
    for field, test in COLUMN_RULES:
        for i, h in enumerate(header):
            ph = _plain(h)
            if i not in used and ph and test(ph):
                mapping[field] = i
                used.add(i)
                break
    return mapping


def parse(path):
    """Rows of one export file → list of dicts (supplier_nif, supplier_name, number, atcud, date,
    type, sector, status, base, vat, total). Raises ValueError if it doesn't look like an export."""
    with open(path, "rb") as f:
        text = _decode(f.read())
    sample = text[:4096]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    # The header is the first row with several recognisable column names (exports may start with a title)
    head_i = next((i for i, r in enumerate(rows[:15]) if len(_map_columns(r)) >= 4), None)
    if head_i is None:
        raise ValueError("This doesn't look like an e-Fatura export (no recognisable columns).")
    cols = _map_columns(rows[head_i])
    if "total" not in cols or not ({"supplier_nif", "supplier"} & set(cols)):
        raise ValueError("The e-Fatura export is missing the supplier or total columns.")
    out = []
    for r in rows[head_i + 1:]:
        if not any(c.strip() for c in r):
            continue
        get = lambda k: r[cols[k]].strip() if k in cols and cols[k] < len(r) else ""  # noqa: E731
        nif, name = get("supplier_nif"), get("supplier_name")
        if not nif and get("supplier"):  # "500000001 - Livraria Exemplo Lda"
            m = re.match(r"^\s*(?:PT)?(\d{9})\s*[-–:]?\s*(.*)$", get("supplier"))
            nif, name = (m.group(1), m.group(2).strip()) if m else ("", get("supplier"))
        nif = re.sub(r"\D", "", nif)[-9:]
        number, atcud = get("number"), get("atcud")
        if " / " in number and not atcud:  # "FT A/29 / JFAB1234-29"
            left, right = number.rsplit(" / ", 1)
            if ATCUD.match(right.strip()):
                number, atcud = left.strip(), right.strip()
        doc_type = get("type")
        total = _number(get("total"))
        if total is None:
            continue
        credit = "credito" in _plain(doc_type) or _plain(doc_type).startswith("nc")
        out.append({
            "supplier_nif": nif, "supplier_name": name, "number": number, "atcud": atcud,
            "date": _date(get("date")), "type": doc_type, "credit_note": credit,
            "sector": get("sector"), "status": get("status"),
            "base": _number(get("base")), "vat": _number(get("vat")), "total": abs(total),
        })
    return out


# ------------------------------------------------------------------ storage (per client folder)
def _db():
    db = history._db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS efatura (
            project TEXT, supplier_nif TEXT, number TEXT, date TEXT, row_json TEXT, imported_at TEXT,
            PRIMARY KEY (project, supplier_nif, number, date)
        );
    """)
    return db


def import_files(project, paths):
    """Adds the rows of one or more export files to the client's e-Fatura list. Returns (added, total)."""
    project = os.path.abspath(project)
    rows = [r for p in paths for r in parse(p)]
    now = datetime.datetime.now().isoformat(timespec="seconds")
    added = 0
    with history._lock:
        db = _db()
        for r in rows:
            key_number = norm_number(r["number"]) or f"{r['date']}|{r['total']:.2f}"
            cur = db.execute("INSERT OR REPLACE INTO efatura VALUES (?,?,?,?,?,?)",
                             (project, r["supplier_nif"], key_number, r["date"],
                              json.dumps(r, ensure_ascii=False), now))
            added += cur.rowcount > 0
        db.commit()
    return len(rows), stored_count(project)


def stored_count(project):
    with history._lock:
        return _db().execute("SELECT COUNT(*) FROM efatura WHERE project=?",
                             (os.path.abspath(project),)).fetchone()[0]


def rows(project, start=None, end=None):
    sql, args = "SELECT row_json FROM efatura WHERE project=?", [os.path.abspath(project)]
    if start:
        sql += " AND date >= ?"; args.append(start)
    if end:
        sql += " AND date <= ?"; args.append(end)
    with history._lock:
        return [json.loads(r[0]) for r in _db().execute(sql + " ORDER BY date", args).fetchall()]


def clear(project):
    with history._lock:
        _db().execute("DELETE FROM efatura WHERE project=?", (os.path.abspath(project),))
        _db().commit()


# ------------------------------------------------------------------ comparison
def compare(project, start=None, end=None):
    """Compares the client's invoices (history) with the imported e-Fatura rows for a period.

    Returns a dict of lists:
      matched     [(invoice, efatura_row, how)]   how = "number" | "probable" (same NIF+date+total)
      differ      [(invoice, efatura_row, [differences])]
      missing     [efatura_row]  — in e-Fatura, no receipt in the folder
      not_in_ef   [invoice]      — receipt in the folder, not in e-Fatura
    """
    invoices = history.query(start, end, project)
    ef = rows(project, start, end)
    by_number = {}
    for i, r in enumerate(ef):
        by_number.setdefault((r["supplier_nif"], norm_number(r["number"])), []).append(i)
    used = set()
    result = {"matched": [], "differ": [], "missing": [], "not_in_ef": []}

    def nif_of(inv):
        v = inv["values"]
        return re.sub(r"\D", "", str(v.get("_nif") or v.get("supplier_nif") or ""))[-9:]

    pending = []
    for inv in invoices:
        v = inv["values"]
        key = (nif_of(inv), norm_number(v.get("invoice_number")))
        cands = [i for i in by_number.get(key, []) if i not in used] if key[1] else []
        if not cands and key[1]:  # NIF unknown (no QR): match on the number alone if it's unique
            same = [i for (n, num), idx in by_number.items() if num == key[1] for i in idx if i not in used]
            cands = same if len(same) == 1 else []
        if cands:
            i = cands[0]
            used.add(i)
            diffs = _differences(v, ef[i])
            (result["differ"] if diffs else result["matched"]).append(
                (inv, ef[i], diffs) if diffs else (inv, ef[i], "number"))
        else:
            pending.append(inv)
    # Second pass: no number match → same NIF (if known) + date + total
    for inv in pending:
        v = inv["values"]
        nif = nif_of(inv)
        cands = [i for i, r in enumerate(ef) if i not in used and r["date"] == str(v.get("date") or "")[:10]
                 and _same_amount(v.get("total_value"), r["total"]) and (not nif or r["supplier_nif"] == nif)]
        if len(cands) == 1:
            used.add(cands[0])
            result["matched"].append((inv, ef[cands[0]], "probable"))
        else:
            result["not_in_ef"].append(inv)
    result["missing"] = [r for i, r in enumerate(ef) if i not in used]
    return result


def _same_amount(a, b):
    try:
        return a is not None and b is not None and abs(float(a) - float(b)) < 0.01
    except (TypeError, ValueError):
        return False


def _differences(values, row):
    out = []
    if values.get("date") and row["date"] and str(values["date"])[:10] != row["date"]:
        out.append(f"date {str(values['date'])[:10]} vs e-Fatura {row['date']}")
    if values.get("total_value") not in (None, "") and not _same_amount(values.get("total_value"), row["total"]):
        out.append(f"total {values.get('total_value')} vs e-Fatura {row['total']:.2f}")
    return out


# ------------------------------------------------------------------ what the user decided per case
def _rdb():
    db = _db()
    db.execute("CREATE TABLE IF NOT EXISTS efatura_resolved (project TEXT, item TEXT, resolution TEXT, at TEXT, "
               "PRIMARY KEY (project, item))")
    return db


def row_key(r):
    """Stable id of an e-Fatura row (for 'not needed')."""
    return f"ef:{r['supplier_nif']}|{norm_number(r['number']) or ''}|{r['date']}|{r['total']:.2f}"


def invoice_key(inv):
    return f"inv:{inv['hash']}"


def resolutions(project):
    with history._lock:
        return dict(_rdb().execute("SELECT item, resolution FROM efatura_resolved WHERE project=?",
                                   (os.path.abspath(project),)).fetchall())


def resolve(project, item, resolution):
    """resolution: e.g. 'not_needed', 'kept', 'registered'; None undoes it."""
    with history._lock:
        db = _rdb()
        if resolution:
            db.execute("INSERT OR REPLACE INTO efatura_resolved VALUES (?,?,?,?)",
                       (os.path.abspath(project), item, resolution,
                        datetime.datetime.now().isoformat(timespec="seconds")))
        else:
            db.execute("DELETE FROM efatura_resolved WHERE project=? AND item=?", (os.path.abspath(project), item))
        db.commit()
