"""Documents that hold several invoices (a Via Verde statement with invoices from four companies, an
EDP bill with a separate invoice for the audiovisual contribution).

The file keeps its own values (the statement's date, total and number); its invoices are stored in
values["_invoices"] (see qr_at.merge_invoices). Everything that counts invoices — e-Fatura matching,
the Excel (one row per invoice), renaming one copy per invoice — goes through here.
"""

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
