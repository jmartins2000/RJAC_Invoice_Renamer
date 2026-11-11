"""The accountant's own e-Fatura workbook ("Conferência EF"): one workbook per client, one sheet per
year, each quarter's portal export pasted at the bottom, and a status code typed per document.

  read(path)                     → what's in it: client, code list, one layout + documents per year sheet,
                                   and a check report (counts and totals against his own SUBTOTALs)
  import_workbook(project, path) → stores the documents and codes in the client (app = source of truth)
  export_workbook(project, out)  → a copy of his workbook with the client's current data written in:
                                   codes updated, new documents added below, missing years added.
                                   His formatting, formulas and other sheets stay as they are.

Only the LAYOUT is detected (which row is the header, which column holds what); values are always
copied straight from the cells.
"""
import copy
import datetime
import json
import os
import re
import shutil

import openpyxl
from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter

from src.services import efatura, history

YEAR = re.compile(r"^(19|20)\d\d$")


def _is_code_header(h):
    h = efatura._plain(h)
    return "controlo" not in h and (h in ("cod", "cod.", "codigo", "codigo estado", "estado cod.")
                                    or "inserir" in h or h.startswith("cod."))


# ------------------------------------------------------------------ reading
def _open(path, data_only=False):
    return openpyxl.load_workbook(path, data_only=data_only, keep_vba=path.lower().endswith(".xlsm"))


def _codes_from(wb):
    """His code list (e.g. sheet "Dados": 1 DOC. OK, 2 EM ANÁLISE…) and client name/NIF, if present."""
    codes, name, nif = [], "", ""
    for ws in wb.worksheets:
        if "dados" not in efatura._plain(ws.title):
            continue
        for row in ws.iter_rows(min_row=1, max_row=60, values_only=True):
            cells = list(row)
            for i, v in enumerate(cells):
                label = efatura._plain(v)
                nxt = cells[i + 1] if i + 1 < len(cells) else None
                if label.startswith(("designa", "nome")) and nxt and not name:
                    name = efatura._cell(nxt)
                elif label.startswith("nif") and nxt and not nif:
                    nif = re.sub(r"\D", "", efatura._cell(nxt))
                elif isinstance(v, int) and not isinstance(v, bool) and 0 < v < 100 \
                        and isinstance(nxt, str) and nxt.strip():
                    codes.append({"code": v, "label": nxt.strip()})
    seen, out = set(), []
    for c in codes:
        if c["code"] not in seen:
            seen.add(c["code"])
            out.append(c)
    return sorted(out, key=lambda c: c["code"]), name, nif


def _year_of(ws, rows):
    if YEAR.match(ws.title.strip()):
        return int(ws.title.strip())
    for r in rows[:10]:
        for i, v in enumerate(r):
            if efatura._plain(v).startswith("ano") and i + 1 < len(r) and YEAR.match(efatura._cell(r[i + 1])):
                return int(efatura._cell(r[i + 1]))
    return None


def find_layout(ws, rows):
    """Header row + columns of one sheet, or None if it isn't a sheet of e-Fatura documents.
    rows: the sheet's cell values (lists), from row 1."""
    for i, r in enumerate(rows[:30]):
        header = [efatura._cell(c) for c in r]
        cols = efatura._map_columns(header)
        if len(cols) >= 4 and "total" in cols and ({"supplier", "supplier_nif"} & set(cols)):
            code_col = next((j for j, h in enumerate(header) if h and _is_code_header(h)), None)
            return {"sheet": ws.title, "header_row": i + 1, "cols": cols, "code_col": code_col,
                    "number_has_atcud": "atcud" in efatura._plain(header[cols["number"]]) if "number" in cols else False}
    return None


def _code_value(v, by_label):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None, None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return (int(v), None) if float(v).is_integer() else (None, str(v))
    text = str(v).strip()
    if text.isdigit():
        return int(text), None
    code = by_label.get(efatura._plain(text))
    return (code, None) if code else (None, text)


def _subtotals(ws_f, ws_v, layout, upto):
    """His SUBTOTAL(9, X6:X505) cells above the data: {field: (value, first_row, last_row)}."""
    out = {}
    by_col = {v: k for k, v in layout["cols"].items()}
    for row in ws_f.iter_rows(min_row=1, max_row=upto):
        for c in row:
            f = c.value
            if isinstance(f, str) and f.upper().startswith("=SUBTOTAL(9,"):
                m = re.search(r"\$?([A-Z]+)\$?(\d+):\$?[A-Z]+\$?(\d+)", f)
                if not m:
                    continue
                col = openpyxl.utils.column_index_from_string(m.group(1)) - 1
                field = by_col.get(col)
                if field in ("total", "vat", "base"):
                    val = ws_v.cell(row=c.row, column=c.column).value
                    out[field] = (float(val) if isinstance(val, (int, float)) else None, int(m.group(2)), int(m.group(3)))
    return out


def _signature(header):
    """A sheet's header row as a key, to recognise the same layout next time."""
    return "|".join(efatura._plain(efatura._cell(c)) for c in header).rstrip("|")


def _saved_layout(ws, rows, saved):
    """A layout the user confirmed before for this client, if this sheet has the same header row."""
    for i, r in enumerate(rows[:40]):
        sig = _signature(r)
        if sig and sig in saved:
            lay = dict(saved[sig])
            return {**lay, "sheet": ws.title, "header_row": i + 1}
    return None


def read(path, overrides=None, saved=None, skip=()):
    """Everything in his workbook, with a check report per year sheet.
    overrides: {sheet: layout} chosen by the user (or the agent) for this import;
    saved: {signature: layout} remembered for this client; skip: sheets to leave out."""
    overrides, saved = overrides or {}, saved or {}
    wb_v = _open(path, data_only=True)  # cached values (what Excel last calculated)
    wb_f = _open(path)                  # formulas (to find his SUBTOTAL ranges)
    codes, client_name, client_nif = _codes_from(wb_v)
    by_label = {efatura._plain(c["label"]): c["code"] for c in (codes or efatura.CODES)}
    sheets = []
    for ws in wb_v.worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        if ws.title in skip:
            continue
        layout = overrides.get(ws.title) or _saved_layout(ws, rows, saved) or find_layout(ws, rows)
        if not layout:
            continue
        layout = {**layout, "cols": {k: int(v) for k, v in layout["cols"].items()}, "sheet": ws.title}
        layout.setdefault("number_has_atcud", False)
        layout.setdefault("code_col", None)
        year = layout.get("year") or _year_of(ws, rows)
        cols, h = layout["cols"], layout["header_row"]
        docs, skipped, unknown_codes = [], [], []
        first = last = None
        for n, r in enumerate(rows[h:], start=h + 1):
            get = lambda k: r[cols[k]] if k in cols and cols[k] < len(r) else None  # noqa: E731
            has_supplier = efatura._cell(get("supplier") or get("supplier_nif") or get("supplier_name"))
            if not has_supplier:
                continue
            doc = efatura.build_row(get)
            if not doc:
                skipped.append(n)
                continue
            raw_code = r[layout["code_col"]] if layout["code_col"] is not None and layout["code_col"] < len(r) else None
            code, odd = _code_value(raw_code, by_label)
            if odd:
                unknown_codes.append((n, odd))
            docs.append({"row": n, "doc": doc, "code": code})
            first = first or n
            last = n
        subtotals = _subtotals(wb_f[ws.title], ws, layout, max(h, (first or h) - 1))
        hidden = {r for r, d in ws.row_dimensions.items() if d.hidden}
        checks = []
        uncalculated = any(v is None for v, _a, _b in subtotals.values())
        for field, (value, a, b) in subtotals.items():
            if value is None:
                continue
            col = cols[field]
            # What Excel's SUBTOTAL adds: numeric cells in its range, visible rows only.
            excel_sum = sum(rows[r - 1][col] for r in range(a, min(b, len(rows)) + 1)
                            if r not in hidden and col < len(rows[r - 1])
                            and isinstance(rows[r - 1][col], (int, float)) and not isinstance(rows[r - 1][col], bool))
            ours = sum(d["doc"][field] for d in docs if d["doc"].get(field) is not None)
            text_cells = [d for d in docs if col < len(rows[d["row"] - 1]) and isinstance(rows[d["row"] - 1][col], str)
                          and rows[d["row"] - 1][col].strip()]
            checks.append({
                "field": field, "his": round(value, 2), "excel": round(excel_sum, 2), "ours": round(ours, 2),
                "ok": abs(excel_sum - value) < 0.015, "range": f"{a}–{b}",
                "outside": sum(1 for d in docs if not (a <= d["row"] <= b)),
                "hidden": sum(1 for d in docs if d["row"] in hidden),
                "text": len(text_cells), "text_sum": round(sum(d["doc"][field] or 0 for d in text_cells), 2),
            })
        sheets.append({
            "sheet": ws.title, "year": year, "layout": layout, "first_row": first, "last_row": last,
            "documents": docs, "skipped_rows": skipped, "unknown_codes": unknown_codes, "checks": checks,
            "uncalculated": uncalculated,
        })
    return {"path": path, "client_name": client_name, "client_nif": client_nif,
            "codes": codes, "sheets": sheets}


def report(info):
    """Short, human summary of read() for the import screen."""
    out = []
    for s in info["sheets"]:
        n = len(s["documents"])
        coded = sum(1 for d in s["documents"] if d["code"])
        notes = []
        for c in s["checks"]:
            label = {"total": "Total", "vat": "IVA", "base": "Base"}[c["field"]]
            if c["ok"]:
                notes.append(f"{label}: read correctly (his SUBTOTAL {c['his']:,.2f} agrees); "
                             f"all {n} documents add up to {c['ours']:,.2f}")
            else:
                notes.append(f"{label}: his SUBTOTAL says {c['his']:,.2f} but the cells add up to {c['excel']:,.2f}. Check this sheet")
        first_check = s["checks"][0] if s["checks"] else None
        if first_check:
            if any(c["text"] for c in s["checks"]):
                parts = ", ".join(f"{c['text']} in {dict(total='Total', vat='IVA', base='Base')[c['field']]} "
                                  f"({c['text_sum']:,.2f})" for c in s["checks"] if c["text"])
                notes.append(f"amounts typed as text (e.g. '1.200,00 €'), which Excel leaves out of his SUBTOTAL: "
                             f"{parts}. The app reads them")
            if first_check["hidden"]:
                notes.append(f"a filter was on when the file was saved ({first_check['hidden']} rows hidden), "
                             "so his SUBTOTAL only counts the visible rows")
            if first_check["outside"]:
                notes.append(f"{first_check['outside']} documents are below his SUBTOTAL range ({first_check['range']})")
        if s["skipped_rows"]:
            notes.append(f"rows without a total, not imported: {', '.join(map(str, s['skipped_rows'][:10]))}"
                         + ("…" if len(s["skipped_rows"]) > 10 else ""))
        if s["unknown_codes"]:
            notes.append("codes not in the list: " + ", ".join(f"row {r} '{v}'" for r, v in s["unknown_codes"][:5]))
        if not s["checks"] and s.get("uncalculated"):
            notes.append("totals not checked: the file has no calculated totals to compare with "
                         "(open it in Excel and save it once, then import again to check)")
        ok = all(c["ok"] for c in s["checks"]) and not s["unknown_codes"]
        out.append({"sheet": s["sheet"], "year": s["year"], "documents": n, "coded": coded,
                    "ok": ok, "checked": bool(s["checks"]), "notes": notes})
    return out


# ------------------------------------------------------------------ the client's workbook (stored)
def _wdb():
    db = efatura._db()
    db.execute("CREATE TABLE IF NOT EXISTS efatura_workbook (project TEXT PRIMARY KEY, original TEXT, "
               "copy TEXT, codes_json TEXT, imported_at TEXT)")
    if "layouts_json" not in {r[1] for r in db.execute("PRAGMA table_info(efatura_workbook)")}:
        db.execute("ALTER TABLE efatura_workbook ADD COLUMN layouts_json TEXT")
    return db


def info(project):
    """The client's imported workbook, or None."""
    with history._lock:
        r = _wdb().execute("SELECT original, copy, codes_json, imported_at FROM efatura_workbook WHERE project=?",
                           (os.path.abspath(project),)).fetchone()
    if not r:
        return None
    return {"original": r[0], "copy": r[1], "codes": json.loads(r[2] or "[]"), "imported_at": r[3],
            "name": os.path.basename(r[0])}


def codes_for(project):
    """The client's code list: from his workbook if it has one, else the default list (with colours)."""
    w = info(project)
    if not w or not w["codes"]:
        return efatura.CODES
    colours = {c["code"]: c for c in efatura.CODES}
    return [{**c, "color": colours.get(c["code"], {}).get("color", ""),
             "text": colours.get(c["code"], {}).get("text", "000000")} for c in w["codes"]]


def saved_layouts(project):
    with history._lock:
        r = _wdb().execute("SELECT layouts_json FROM efatura_workbook WHERE project=?",
                           (os.path.abspath(project),)).fetchone()
    return json.loads(r[0]) if r and r[0] else {}


def _layouts_to_save(path, data):
    """Signature → layout for every sheet that was read (so the next import of this client's
    workbook needs no help)."""
    wb = _open(path, data_only=True)
    out = {}
    for s in data["sheets"]:
        lay = s["layout"]
        row = [c.value for c in wb[s["sheet"]][lay["header_row"]]]
        out[_signature(row)] = {"cols": lay["cols"], "code_col": lay["code_col"],
                                "number_has_atcud": lay.get("number_has_atcud", False)}
    return out


def import_workbook(project, path, data=None):
    """Stores every document and code of his workbook in the client. His codes win over the app's.
    Returns {"report": [...], "new": n, "documents": n, "client_name", "client_nif"}."""
    project = os.path.abspath(project)
    data = data or read(path)
    if not data["sheets"]:
        raise ValueError("No sheet in this workbook looks like a list of e-Fatura documents.")
    docs = [d for s in data["sheets"] for d in s["documents"]]
    new = efatura.store_rows(project, [d["doc"] for d in docs])
    for d in docs:
        if d["code"]:
            efatura.set_code(project, efatura.row_key(d["doc"]), d["code"])
    # keep a copy: it's the template the export writes into (and goes along with feedback)
    folder = efatura.exports_dir(project)
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    kept = os.path.join(folder, f"{stamp} {os.path.basename(path)}")
    shutil.copy2(path, kept)
    layouts = {**saved_layouts(project), **_layouts_to_save(path, data)}  # before taking the lock
    with history._lock:
        db = _wdb()
        db.execute("INSERT OR REPLACE INTO efatura_workbook (project, original, copy, codes_json, imported_at, "
                   "layouts_json) VALUES (?,?,?,?,?,?)",
                   (project, os.path.abspath(path), kept, json.dumps(data["codes"], ensure_ascii=False),
                    datetime.datetime.now().isoformat(timespec="seconds"), json.dumps(layouts, ensure_ascii=False)))
        db.commit()
    return {"report": report(data), "new": new, "documents": len(docs),
            "client_name": data["client_name"], "client_nif": data["client_nif"]}


def forget(project):
    with history._lock:
        db = _wdb()
        db.execute("DELETE FROM efatura_workbook WHERE project=?", (os.path.abspath(project),))
        db.commit()


# ------------------------------------------------------------------ writing back
def _doc_key(doc):
    return efatura.row_key(doc)


def _write_doc(ws, row, layout, doc, code, style_row):
    cols = layout["cols"]

    def put(field, value):
        if field not in cols:
            return
        c = ws.cell(row=row, column=cols[field] + 1, value=value)
        if style_row:
            c._style = copy.copy(ws.cell(row=style_row, column=cols[field] + 1)._style)

    supplier = f"{doc['supplier_nif']} - {doc['supplier_name']}".strip(" -")
    if "supplier" in cols:
        put("supplier", supplier)
    put("supplier_nif", doc["supplier_nif"])
    put("supplier_name", doc["supplier_name"])
    number = doc["number"]
    if layout.get("number_has_atcud") and doc.get("atcud"):
        number = f"{number} / {doc['atcud']}"
    put("number", number)
    if not layout.get("number_has_atcud"):
        put("atcud", doc.get("atcud") or None)
    try:
        put("date", datetime.datetime.fromisoformat(doc["date"]) if doc.get("date") else None)
    except ValueError:
        put("date", doc.get("date"))
    put("type", doc.get("type") or None)
    put("sector", doc.get("sector") or None)
    put("status", doc.get("status") or None)
    put("total", doc["total"])
    put("vat", doc.get("vat"))
    put("base", doc.get("base"))
    if layout["code_col"] is not None:
        c = ws.cell(row=row, column=layout["code_col"] + 1, value=code)
        if style_row:
            c._style = copy.copy(ws.cell(row=style_row, column=layout["code_col"] + 1)._style)


def _fill_formulas(ws, row, from_row, data_cols):
    """Copies the formulas of his other columns (month, description, VAT splits…) to a new row."""
    for c in ws[from_row]:
        if c.column - 1 in data_cols:
            continue
        target = ws.cell(row=row, column=c.column)
        if isinstance(c.value, str) and c.value.startswith("=") and target.value in (None, ""):
            target.value = Translator(c.value, origin=c.coordinate).translate_formula(target.coordinate)
            target._style = copy.copy(c._style)


def _new_year_sheet(wb, template_ws, year, layout, first_row, last_row):
    """A sheet for a year his workbook doesn't have yet: a copy of his latest year sheet, emptied."""
    ws = wb.copy_worksheet(template_ws)
    ws.title = str(year)
    for cf in template_ws.conditional_formatting:
        for rule in cf.rules:
            ws.conditional_formatting.add(str(cf.sqref), rule)
    if template_ws.auto_filter.ref:
        ws.auto_filter.ref = template_ws.auto_filter.ref
    ws.freeze_panes = template_ws.freeze_panes
    data_cols = set(layout["cols"].values()) | ({layout["code_col"]} if layout["code_col"] is not None else set())
    for r in range(first_row, ws.max_row + 1):  # every document row (incl. ones written in this export)
        for c in data_cols:
            ws.cell(row=r, column=c + 1).value = None
    # the year shown in the header, if it's written as a plain value
    for row in ws.iter_rows(min_row=1, max_row=layout["header_row"]):
        for c in row:
            if c.value == template_ws.title or (isinstance(c.value, int) and YEAR.match(str(c.value))
                                                 and str(c.value) == template_ws.title):
                c.value = year if isinstance(c.value, int) else str(year)
    # keep sheets in year order
    years = [(int(s.title), s) for s in wb.worksheets if YEAR.match(s.title) and s is not ws]
    later = [s for y, s in years if y > year]
    earlier = [s for y, s in years if y < year]
    target = wb.worksheets.index(later[0]) if later else (wb.worksheets.index(earlier[-1]) + 1 if earlier else 0)
    wb.move_sheet(ws, offset=target - wb.worksheets.index(ws))
    return ws


def export_workbook(project, out_path):
    """Writes the client's documents and codes into a copy of his workbook. Returns a summary."""
    w = info(project)
    if not w or not os.path.exists(w["copy"]):
        raise ValueError("This client has no workbook imported.")
    data = read(w["copy"], saved=saved_layouts(project))
    wb = _open(w["copy"])
    app_codes = efatura.codes(project)
    view = efatura.compare(project)
    auto = {efatura.row_key(r) for _inv, r, _how in view["matched"]}
    by_year = {}
    for doc in efatura.rows(project):
        by_year.setdefault((doc.get("date") or "")[:4], []).append(doc)
    summary = {"added": 0, "codes_changed": 0, "new_sheets": []}
    sheets = {s["year"]: s for s in data["sheets"] if s["year"]}
    latest = max(sheets) if sheets else None
    for year_s in sorted(y for y in by_year if YEAR.match(y)):
        year = int(year_s)
        if year in sheets:
            s = sheets[year]
            ws = wb[s["sheet"]]
        else:
            if latest is None:
                continue
            t = sheets[latest]
            ws = _new_year_sheet(wb, wb[t["sheet"]], year, t["layout"], t["first_row"] or t["layout"]["header_row"] + 1,
                                 t["last_row"])
            s = {**t, "sheet": ws.title, "documents": [], "first_row": None,
                 "last_row": None, "_start": t["first_row"] or t["layout"]["header_row"] + 1}
            summary["new_sheets"].append(ws.title)
        layout = s["layout"]
        present = {_doc_key(d["doc"]): d for d in s["documents"]}
        data_cols = set(layout["cols"].values()) | ({layout["code_col"]} if layout["code_col"] is not None else set())
        style_row = s["last_row"] or s.get("_start")
        next_row = (s["last_row"] + 1) if s["last_row"] else s.get("_start", layout["header_row"] + 1)
        for doc in by_year[year_s]:  # already by date, then import order
            key = _doc_key(doc)
            code = app_codes.get(key) or (1 if key in auto else None)
            if key in present:
                d = present[key]
                if code and code != d["code"] and layout["code_col"] is not None:
                    ws.cell(row=d["row"], column=layout["code_col"] + 1, value=code)
                    summary["codes_changed"] += 1
                continue
            _write_doc(ws, next_row, layout, doc, code, style_row if style_row and style_row != next_row else None)
            if style_row and style_row != next_row:
                _fill_formulas(ws, next_row, style_row, data_cols)
            next_row += 1
            summary["added"] += 1
    root, ext = os.path.splitext(out_path)
    if os.path.splitext(w["copy"])[1].lower() == ".xlsm" and ext.lower() != ".xlsm":
        out_path = root + ".xlsm"
    wb.calculation.fullCalcOnLoad = True  # Excel recalculates his formulas and SUBTOTALs on opening
    wb.save(out_path)
    summary["path"] = out_path
    return summary


# ------------------------------------------------------------------ preview (for mapping by hand)
FIELDS = [  # what a column can be, in the order shown to the user
    ("supplier", "Supplier (NIF - name)"), ("supplier_nif", "Supplier NIF"), ("supplier_name", "Supplier name"),
    ("number", "Document number"), ("atcud", "ATCUD / control code"), ("date", "Date"), ("type", "Type"),
    ("sector", "Sector"), ("status", "Status"), ("total", "Total"), ("vat", "IVA"), ("base", "Base"),
    ("code", "Code"),
]


def _show(v):
    if v is None:
        return ""
    if isinstance(v, datetime.datetime):
        return v.date().isoformat() if not (v.hour or v.minute) else v.isoformat(sep=" ", timespec="minutes")
    if isinstance(v, float):
        return f"{v:.2f}" if abs(v) < 1e12 else str(v)
    return str(v)[:60]


def preview(path, project=None, rows=40, cols=20):
    """Each sheet's first rows as text + how the app would read it now (or None if it can't tell)."""
    wb = _open(path, data_only=True)
    saved = saved_layouts(project) if project else {}
    out = []
    for ws in wb.worksheets:
        values = [list(r) for r in ws.iter_rows(values_only=True)]
        filled = sum(1 for r in values if sum(1 for c in r if c not in (None, "")) >= 3)
        layout = _saved_layout(ws, values, saved) or find_layout(ws, values)
        if layout:
            layout = {**layout, "year": _year_of(ws, values)}
        width = min(cols, max((len(r) for r in values[:rows]), default=0))
        out.append({
            "sheet": ws.title, "rows": [[_show(c) for c in (r + [None] * width)[:width]] for r in values[:rows]],
            "total_rows": len(values), "layout": layout, "year": _year_of(ws, values),
            "looks_like_data": filled >= 5 and "dados" not in efatura._plain(ws.title),
        })
    return out


def try_layout(path, sheet, layout):
    """What a mapping would import from one sheet: counts, total and a few example documents."""
    data = read(path, overrides={sheet: layout}, skip=())
    s = next((x for x in data["sheets"] if x["sheet"] == sheet), None)
    if not s:
        return {"documents": 0, "coded": 0, "total": 0, "examples": []}
    docs = s["documents"]
    return {"documents": len(docs), "coded": sum(1 for d in docs if d["code"]),
            "total": round(sum(d["doc"]["total"] for d in docs), 2), "skipped": len(s["skipped_rows"]),
            "examples": [{**d["doc"], "code": d["code"], "row": d["row"]} for d in docs[:3]],
            "notes": report({"sheets": [s]})[0]["notes"]}
