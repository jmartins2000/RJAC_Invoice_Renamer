"""The fields read from each invoice, configurable by the user.

Each field says what Gemini should look for, its type, and whether it goes into the
filename and/or the Excel. Built-in fields can be switched off but not deleted; the user
can add their own. The order of the list is the order in the filename and the Excel.
"""
import re
from dataclasses import asdict, dataclass

SEPARATORS = {" ~ ": "Tilde  ( ~ )", " - ": "Dash  ( - )", " _ ": "Underscore  ( _ )", " ": "Space"}
DEFAULT_SEPARATOR = " ~ "
TYPES = ("text", "number", "date")


@dataclass
class FieldDef:
    key: str
    label: str
    instructions: str
    type: str = "text"          # text | number | date
    enabled: bool = True        # extracted at all
    in_filename: bool = False
    in_excel: bool = True
    builtin: bool = False


BUILTIN = [
    FieldDef("date", "Date",
             'The issue/invoice date ("Data", "Data de emissão", "Invoice date", "Date of issue"). '
             "Prefer the issue date over due dates or service periods.",
             "date", True, True, True, True),
    FieldDef("total_value", "Total",
             'The grand total charged, including taxes ("Total", "Total a pagar", "Amount due", "Total (EUR)"). '
             "For credit notes or refunds, use the positive amount.",
             "number", True, True, True, True),
    FieldDef("invoice_number", "Invoice no.",
             'The document\'s own identifier, e.g. labelled "Fatura", "Fatura-Recibo", "FR", "FT", "Nº", '
             '"Invoice number", "Receipt number". Copy it exactly, keeping spaces, slashes and hyphens. '
             "Not customer numbers, NIF/VAT numbers, order numbers or ATCUD codes.",
             "text", True, True, True, True),
    FieldDef("supplier", "Supplier",
             "The name of the business that ISSUED the document (the seller), not the customer.",
             "text", True, True, True, True),
]

# Ready-made extras, off until the user switches them on.
PRESETS = [
    FieldDef("supplier_nif", "Supplier NIF",
             "The tax number (NIF / VAT ID / Contribuinte) of the business that issued the document, "
             "without country prefix spaces. Not the customer's NIF.",
             "text", False, False, True, True),
    FieldDef("net_amount", "Net amount",
             'The total before VAT ("Total ilíquido", "Incidência", "Subtotal", "Net").', "number",
             False, False, True, True),
    FieldDef("vat_amount", "VAT",
             'The total VAT/IVA charged ("IVA", "Total IVA", "VAT"). 0 if the document says VAT is exempt '
             "or not applicable.", "number", False, False, True, True),
    FieldDef("vat_rate", "VAT rate",
             'The VAT/IVA rate(s) applied, e.g. "23%" or "6% / 23%".', "text", False, False, True, True),
    FieldDef("currency", "Currency", "ISO 4217 code of the total, e.g. EUR, USD.", "text",
             False, False, True, True),
]

# Pseudo-field for the filename only (not extracted).
ORIGINAL = "original"


def defaults():
    return [FieldDef(**asdict(f)) for f in BUILTIN + PRESETS]


def from_settings(raw):
    """Stored list of dicts → FieldDefs, adding any built-ins/presets missing from older settings."""
    if not raw:
        return defaults()
    out, seen = [], set()
    for d in raw:
        try:
            f = FieldDef(**{k: d[k] for k in FieldDef.__dataclass_fields__ if k in d})
        except TypeError:
            continue
        if f.key not in seen:
            out.append(f)
            seen.add(f.key)
    for f in defaults():
        if f.key not in seen:
            out.append(f)
    return out


def to_settings(fields):
    return [asdict(f) for f in fields]


def make_key(label, existing):
    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "field"
    if base in ("is_invoice", ORIGINAL):
        base = f"custom_{base}"
    key, i = base, 2
    while key in existing:
        key, i = f"{base}_{i}", i + 1
    return key


def load():
    from src.services import settings
    return from_settings(settings.load().get("fields"))


def save(fields):
    from src.services import settings
    settings.save(fields=to_settings(fields))


def json_schema(fields):
    """Response schema for Gemini: is_invoice + every enabled field (nullable)."""
    props = {"is_invoice": {"type": "boolean",
                            "description": "True only for invoices, receipts, credit notes or similar billing documents."}}
    for f in fields:
        if not f.enabled:
            continue
        if f.type == "number":
            props[f.key] = {"type": "number", "nullable": True, "description": f.label}
        elif f.type == "date":
            props[f.key] = {"type": "string", "description": f"{f.label}, as YYYY-MM-DD, or empty"}
        else:
            props[f.key] = {"type": "string", "description": f"{f.label}, or empty"}
    return {"type": "object", "properties": props, "required": list(props)}


def prompt(fields):
    lines = [
        "You are reading a single document that is usually a supplier invoice (often Portuguese).",
        "Extract the fields below. Only use information printed in THIS document.",
        "If a field is not present, return an empty string (or null for numbers). Never guess or invent values.",
        "Numbers use a dot as decimal separator (1.234,56 → 1234.56). Dates are YYYY-MM-DD.",
        "",
        "- is_invoice: false if the document is not a billing document (e.g. a slide, letter, contract, "
        "statement). When false, leave every other field empty.",
    ]
    for f in fields:
        if f.enabled:
            lines.append(f"- {f.key} ({f.label}, {f.type}): {f.instructions}")
    return "\n".join(lines)


# ---------------------------------------------------------------- formatting
def display_value(field, value):
    """Value as shown in the form / filename: dates 2026.10.06, numbers 60000.00."""
    if value is None:
        return ""
    if field.type == "number" and isinstance(value, (int, float)):
        return f"{value:.2f}"
    if field.type == "date":
        return str(value).replace("-", ".")
    return str(value)


def parse_value(field, text):
    """Form text → stored value (numbers as float when possible, dates as YYYY-MM-DD)."""
    text = (text or "").strip()
    if not text:
        return None if field.type == "number" else ""
    if field.type == "number":
        t = text.replace("€", "").replace("$", "").replace(" ", "")
        if "," in t and "." in t:
            t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
        elif "," in t:
            t = t.replace(",", ".")
        try:
            return float(t)
        except ValueError:
            return text
    if field.type == "date":
        m = re.fullmatch(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
        if m:
            y, mo, d = m.groups()
            return f"{y}-{int(mo):02d}-{int(d):02d}"
    return text


FORBIDDEN = re.compile(r'[<>:"/\\|?*]')


def separator_problem(sep):
    """None if `sep` can be used between filename parts, else a short reason."""
    if sep == "":
        return "The separator can't be empty."
    if FORBIDDEN.search(sep) or any(ord(c) < 32 for c in sep):
        return 'Windows doesn\'t allow  < > : " / \\ | ? *  in file names.'
    if len(sep) > 10:
        return "Keep the separator short (10 characters at most)."
    if sep.strip(" .") == "" and sep != " ":
        return "Use at least one visible character (or a single space)."
    return None


def build_filename(values, original_filename, fields, filename_keys, separator):
    """New filename from the chosen fields, or None if empty."""
    by_key = {f.key: f for f in fields}
    parts = []
    for key in filename_keys:
        if key == ORIGINAL:
            continue
        f = by_key.get(key)
        if not f or not f.enabled:
            continue
        text = FORBIDDEN.sub("_", display_value(f, values.get(key))).strip().rstrip(". ")
        if text:
            parts.append(text)
    name = separator.join(parts)
    if ORIGINAL in filename_keys:
        original = __import__("os").path.splitext(original_filename)[0]
        joiner = "_" if separator == " " else separator
        name = f"{name}{joiner}{original}" if name else original
    ext = __import__("os").path.splitext(original_filename)[1].lower() or ".pdf"
    return f"{name}{ext}" if name else None


def parse_filename(filename, fields, filename_keys, separator):
    """Reverse of build_filename. Returns values or None if the name doesn't fit the pattern."""
    if separator == " ":
        return None  # spaces also occur inside values, so this can't be parsed reliably
    stem = __import__("os").path.splitext(filename)[0]
    by_key = {f.key: f for f in fields}
    keys = [k for k in filename_keys if k == ORIGINAL or (k in by_key and by_key[k].enabled)]
    parts = stem.split(separator)
    if ORIGINAL in keys and len(parts) > len(keys):  # the original name may itself contain the separator
        parts = parts[:len(keys) - 1] + [separator.join(parts[len(keys) - 1:])]
    if len(parts) != len(keys):
        return None
    values = {}
    for key, text in zip(keys, parts):
        if key == ORIGINAL:
            continue
        f = by_key[key]
        v = parse_value(f, text)
        if f.type == "number" and not isinstance(v, float):
            return None
        if f.type == "date" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v)):
            return None
        values[key] = v
    return values


def filename_keys(fields, include_original):
    keys = [f.key for f in fields if f.enabled and f.in_filename]
    return keys + [ORIGINAL] if include_original else keys
