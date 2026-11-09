"""Reads the official Portuguese invoice QR code (AT, Portaria 195/2020) from a PDF or image.

It holds certified values: A = supplier NIF, D = document type, F = date (YYYYMMDD),
G = document number, O = total with taxes. Only QR codes in this format are used, so
unrelated QR codes on a document (websites, payments) are ignored.
"""
import re

AT_PATTERN = re.compile(r"^A:\d{9}\*B:")


def _images(path, widths=(1000, 1400, 2200)):
    """Yields (page index, PIL image) at a few resolutions (pages can be tiny, e.g. 32x61 pt scans)."""
    from PIL import Image, ImageOps
    from src.services.file_types import is_image
    if is_image(path):
        yield 0, ImageOps.exif_transpose(Image.open(path)).convert("RGB")  # same orientation as the preview
        return
    import pymupdf
    doc = pymupdf.open(path)
    try:
        for i, page in enumerate(list(doc)[:4]):
            for w in widths:
                z = w / max(page.rect.width, 1)
                pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z))
                yield i, Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()


def parse(text):
    """'A:500052999*B:...*F:20260606*G:FS 1/2*O:50.00*...' → dict, or None if not the AT format."""
    if not text or not AT_PATTERN.match(text.strip()):
        return None
    fields = {}
    for chunk in text.strip().split("*"):
        if ":" in chunk:
            k, v = chunk.split(":", 1)
            fields[k.strip()] = v.strip()
    out = {"supplier_nif": fields.get("A"), "doc_type": fields.get("D"), "invoice_number": fields.get("G")}
    f = fields.get("F", "")
    if re.fullmatch(r"\d{8}", f):
        out["date"] = f"{f[:4]}-{f[4:6]}-{f[6:]}"
    try:
        out["total_value"] = float(fields.get("O", ""))
    except ValueError:
        pass
    try:
        out["vat_amount"] = float(fields.get("N", ""))
        if out.get("total_value") is not None:
            out["net_amount"] = round(out["total_value"] - out["vat_amount"], 2)
    except ValueError:
        pass
    return out if out.get("date") or out.get("total_value") is not None else None


def read(path):
    """The AT QR values of a document, or None (no QR / unreadable / not the AT format).
    Also returns where it is: "page" and "box" = (x0, y0, x1, y1) as fractions of the page."""
    try:
        import zxingcpp
    except ImportError:
        return None
    try:
        from PIL import ImageOps
        gh = zxingcpp.Binarizer.GlobalHistogram
        # Default reader first; then a global black/white threshold, which copes better with
        # crumpled or unevenly lit receipts; then the same on a contrast-stretched grey image.
        strategies = (lambda im: zxingcpp.read_barcodes(im),
                      lambda im: zxingcpp.read_barcodes(im, binarizer=gh),
                      lambda im: zxingcpp.read_barcodes(ImageOps.autocontrast(im.convert("L")), binarizer=gh))
        for page, img in _images(path):
            results = []
            for strategy in strategies:
                results = [r for r in strategy(img) if AT_PATTERN.match(r.text.strip())]
                if results:
                    break
            for r in results:
                parsed = parse(r.text)
                if parsed:
                    p = r.position
                    xs = [p.top_left.x, p.top_right.x, p.bottom_right.x, p.bottom_left.x]
                    ys = [p.top_left.y, p.top_right.y, p.bottom_right.y, p.bottom_left.y]
                    parsed["page"] = page
                    parsed["box"] = (min(xs) / img.width, min(ys) / img.height,
                                     max(xs) / img.width, max(ys) / img.height)
                    return parsed
    except Exception as e:
        print(f"QR read failed for {path}: {e}")
    return None


def apply(values, field_defs, qr):
    """Overwrite values with the QR's certified ones. Returns the list of corrections (may be empty)."""
    from src.services import fields as fieldmod
    enabled = {f.key: f for f in field_defs if f.enabled}
    corrected = []
    if qr.get("supplier_nif"):
        values["_nif"] = qr["supplier_nif"]  # remembered (hidden) so the supplier's name can be reused later
    for key in ("date", "total_value", "invoice_number", "supplier_nif", "vat_amount", "net_amount"):
        if key not in enabled or qr.get(key) in (None, ""):
            continue
        old, new = values.get(key), qr[key]
        if isinstance(new, float):
            try:
                same = old not in (None, "") and abs(float(old) - new) < 0.005
            except (TypeError, ValueError):
                same = False
        else:
            same = str(old or "").replace(" ", "").upper() == str(new).replace(" ", "").upper()
        if not same:
            f = enabled[key]
            if old not in (None, ""):
                corrected.append(f"{f.label} {fieldmod.display_value(f, old)} → {fieldmod.display_value(f, new)}")
            values[key] = new
    return corrected


# Fields the QR code can fill on its own (the supplier's name comes from earlier invoices of the same NIF)
QR_FIELDS = {"date", "total_value", "invoice_number", "supplier_nif", "vat_amount", "net_amount"}


def values_without_ai(qr, field_defs, supplier_name):
    """All enabled values from the QR alone (+ a known supplier name), or None if something is missing."""
    needed = {f.key for f in field_defs if f.enabled}
    values = {"_nif": qr.get("supplier_nif")}
    for key in needed:
        if key == "supplier":
            if not supplier_name:
                return None
            values["supplier"] = supplier_name
        elif key in QR_FIELDS and qr.get(key) not in (None, ""):
            values[key] = qr[key]
        else:
            return None
    return values
