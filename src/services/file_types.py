"""Which files count as invoices: PDFs and images (photos, scans, screenshots)."""
import os

MIME = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp"}
IMAGES = {".png", ".jpg", ".jpeg", ".webp"}


def is_invoice_file(name):
    return not name.startswith(".") and os.path.splitext(name)[1].lower() in MIME


def is_image(name):
    return os.path.splitext(name)[1].lower() in IMAGES


def mime_type(name):
    return MIME.get(os.path.splitext(name)[1].lower(), "application/pdf")


def list_invoices(folder):
    try:
        return sorted((f for f in os.listdir(folder) if is_invoice_file(f) and os.path.isfile(os.path.join(folder, f))),
                      key=str.lower)
    except OSError:
        return []
