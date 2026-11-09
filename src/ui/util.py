"""Small shared UI helpers."""
import os

EXAMPLE = {"date": "2026-10-06", "total_value": 60000.0, "invoice_number": "FT A/29",
           "supplier": "Quociente Invencível Lda", "supplier_nif": "517875845", "net_amount": 48780.49,
           "vat_amount": 11219.51, "vat_rate": "23%", "currency": "EUR"}
EXAMPLE_ORIGINAL = "Fatura FT A-29.pdf"


def shorten(text, limit=52):
    """Middle-ellipsis for long paths."""
    return text if len(text) <= limit else f"{text[:limit // 2 - 1]}…{text[-(limit // 2):]}"


def count_pdfs(folder):
    try:
        return sum(1 for f in os.listdir(folder) if f.lower().endswith(".pdf") and not f.startswith("."))
    except OSError:
        return 0
