"""Reads the official Portuguese invoice QR code (AT, Portaria 195/2020) from a PDF or image.

It holds certified values: A = supplier NIF, D = document type, F = date (YYYYMMDD),
G = document number, O = total with taxes. Only QR codes in this format are used, so
unrelated QR codes on a document (websites, payments) are ignored.
"""
import re

AT_PATTERN = re.compile(r"^A:\d{9}\*B:")


def _images(path, widths=(1400, 2200)):
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
        for page, img in _images(path):
            for r in zxingcpp.read_barcodes(img):
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
