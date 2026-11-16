"""Documents that hold several invoices (a Via Verde statement with invoices from four companies, an
EDP bill with a separate invoice for the audiovisual contribution).

The file keeps its own values (the statement's date, total and number); its invoices are stored in
values["_invoices"] (see qr_at.merge_invoices). Everything that counts invoices — e-Fatura matching,
the Excel (one row per invoice), renaming one copy per invoice — goes through here.
"""

import os

PART_KEYS = ("date", "total_value", "invoice_number", "supplier", "supplier_nif", "vat_amount")


def parts(values):
    """The invoices inside a document ([] for an ordinary single invoice)."""
    p = (values or {}).get("_invoices") or []
    return p if len(p) >= 2 else []


def part_values(values, part):
    """One invoice of a document as ordinary values: the document's other fields + this invoice's own."""
    out = {k: v for k, v in (values or {}).items() if not k.startswith("_")}
    for k in PART_KEYS:
        if part.get(k) not in (None, ""):
            out[k] = part[k]
    if part.get("supplier_nif"):
        out["_nif"] = part["supplier_nif"]
    return out


def expand(values):
    """[values] for a single invoice, or one values dict per invoice inside the document."""
    p = parts(values)
    return [part_values(values, x) for x in p] if p else [values]


def is_credit(part):
    """A credit note (NC) inside a statement: it reduces what's owed."""
    import re
    return str(part.get("doc_type") or "").upper() == "NC" or bool(re.match(r"^\s*NC(\b|\d)", str(part.get("invoice_number") or ""), re.I))


def sum_check(values):
    """(sum of the invoices, the document's total, matches?) — a quick sanity check shown in the review.
    EDP's 'total to pay' can include its own invoices only, so a mismatch is a hint, not an error."""
    p = parts(values)
    s = round(sum((-1 if is_credit(x) else 1) * float(x.get("total_value") or 0) for x in p), 2)
    try:
        total = round(float(values.get("total_value")), 2)
    except (TypeError, ValueError):
        total = None
    return s, total, total is not None and abs(s - total) < 0.01


# ------------------------------------------------------------------ "is this really printed on the PDF?"
import functools
import re
import unicodedata

_STOP = {"sa", "s", "a", "lda", "ltd", "de", "da", "do", "das", "dos", "e", "the", "em", "unipessoal", "sociedade"}


def _plain(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


@functools.lru_cache(maxsize=32)
def _text(path, mtime):
    try:
        import pymupdf
        doc = pymupdf.open(path)
        try:
            return _plain(" ".join(page.get_text() for page in doc))
        finally:
            doc.close()
    except Exception:
        return ""


def pdf_text(path):
    """The PDF's own text layer, simplified ('' for photos and scans without text)."""
    try:
        return _text(path, os.path.getmtime(path)) if path.lower().endswith(".pdf") else ""
    except OSError:
        return ""


def name_in_text(name, text):
    """True if the name is printed in the document, False if not, None if there's no text to check."""
    if not text:
        return None
    words = [w for w in _plain(name).split() if w not in _STOP and len(w) >= 3]
    if not words:
        return None
    found = sum(1 for w in words if re.search(rf"\b{re.escape(w)}\b", text))
    return found >= max(1, round(len(words) * 0.6))


def number_in_text(number, text):
    """True if the number (ignoring spaces, slashes, dots…) is printed in the document."""
    if not text or not str(number or "").strip():
        return None
    digits = re.sub(r"[^a-z0-9]", "", _plain(number))
    return bool(digits) and digits in text.replace(" ", "")


def document_values(values, path):
    """For a statement holding several invoices, the document's own values follow rules instead of the
    model's reading: date = the invoices' (latest) date, total = their sum (credit notes subtract),
    number = kept only if it's really printed on the PDF."""
    p = parts(values)
    if not p:
        return values
    out = dict(values)
    dates = sorted(x.get("date") for x in p if x.get("date"))
    if dates:
        out["date"] = dates[-1]
    out["total_value"] = round(sum((-1 if is_credit(x) else 1) * float(x.get("total_value") or 0) for x in p), 2)
    text = pdf_text(path)
    if out.get("invoice_number") and number_in_text(out["invoice_number"], text) is False:
        out["invoice_number"] = ""
    return out
