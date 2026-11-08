"""Invoice data extraction with Gemini (google-genai SDK)."""
import datetime
import os
import random
import threading
import time

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field

# Chosen with tools/eval_extraction.py (18/18 on the sample set, Nov 2026).
DEFAULT_MODEL = "gemini-3.8-flash"

# Requests above this size are uploaded via the Files API instead of sent inline.
INLINE_LIMIT_BYTES = 18 * 1024 * 1024

MAX_ATTEMPTS = 5

# USD per 1M tokens (input, output). Source: https://aistudio.google.com/docs/pricing (Nov 2026)
def _pricing(model):
    if model == "gemini-3.8-flash":
        return (0.75, 3.75) if datetime.date.today() < datetime.date(2027, 1, 1) else (1.50, 7.50)
    if model == "gemini-3.5-flash-lite":
        return (0.30, 2.50)
    return (1.50, 10.00)  # conservative fallback for other models


class InvoiceData(BaseModel):
    is_invoice: bool = Field(
        description="True only if the document is an invoice, receipt, credit note or similar billing document."
    )
    date: str = Field(description="Issue date as YYYY-MM-DD, or empty string if not present.")
    total_value: float | None = Field(
        description="Grand total actually charged (including taxes), or null if not present."
    )
    currency: str = Field(description="ISO 4217 currency code of the total, e.g. EUR, USD. Empty if unknown.")
    supplier: str = Field(description="Name of the company issuing the document, or empty string.")
    invoice_number: str = Field(description="Document identifier exactly as printed, or empty string.")


PROMPT = """You are reading a single document that is usually a supplier invoice (often Portuguese).
Extract the fields below. Only use information that is printed in THIS document.
If a field is not present, return an empty string (or null for total_value). Never guess or invent values.

- is_invoice: false if the document is not a billing document (e.g. a slide, letter, contract, statement).
  When false, leave every other field empty.
- date: the issue/invoice date ("Data", "Data de emissão", "Invoice date", "Date of issue"), as YYYY-MM-DD.
  Prefer the issue date over due dates or service periods.
- total_value: the grand total charged, as a number ("Total", "Total a pagar", "Amount due", "Total (EUR)").
  Use a dot as the decimal separator (1.234,56 → 1234.56). For credit notes or refunds, use the positive amount.
- currency: the currency of total_value.
- supplier: the business that ISSUED the document (the seller), not the customer it is billed to.
- invoice_number: the document's own identifier, e.g. labelled "Fatura", "Fatura-Recibo", "FR", "FT",
  "Nº", "Invoice number", "Receipt number". Copy it exactly, keeping spaces, slashes and hyphens.
  Do not return customer numbers, NIF/VAT numbers, order numbers or ATCUD codes.
"""


class GeminiService:
    """Extracts invoice fields from PDFs. Thread-safe; tracks token usage for cost display."""

    def __init__(self, api_key, model=None):
        self.client = genai.Client(api_key=api_key)
        self.model = model or os.environ.get("RJAC_MODEL") or DEFAULT_MODEL
        self._lock = threading.Lock()
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def extract_invoice_data(self, file_path):
        """Returns a dict with the extracted fields, or {'error': message} on failure."""
        filename = os.path.basename(file_path)
        try:
            with open(file_path, "rb") as f:
                pdf_bytes = f.read()
            data = self._call_with_retries(pdf_bytes, filename)
            if not data.get("is_invoice", True):
                data["warning"] = "This doesn't look like an invoice. Please check the values."
            print(f"[DONE] {filename}")
            return data
        except Exception as e:
            msg = friendly_error(e)
            print(f"[ERROR] {filename}: {msg}")
            return {"error": msg}

    def _call_with_retries(self, pdf_bytes, filename):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return self._call(pdf_bytes)
            except Exception as e:
                if attempt == MAX_ATTEMPTS or not is_transient(e):
                    raise
                wait = min(60, 2 ** attempt) + random.uniform(0, 1.5)
                print(f"[RETRY {attempt}] {filename}: {friendly_error(e)} — waiting {wait:.0f}s")
                time.sleep(wait)

    def _call(self, pdf_bytes):
        uploaded = None
        if len(pdf_bytes) <= INLINE_LIMIT_BYTES:
            pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
        else:
            import io
            uploaded = self.client.files.upload(
                file=io.BytesIO(pdf_bytes), config={"mime_type": "application/pdf"}
            )
            pdf_part = uploaded
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[pdf_part, PROMPT],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=InvoiceData,
                    temperature=0,
                ),
            )
        finally:
            if uploaded is not None:
                try:
                    self.client.files.delete(name=uploaded.name)
                except Exception:
                    pass

        usage = response.usage_metadata
        if usage:
            with self._lock:
                self.total_input_tokens += usage.prompt_token_count or 0
                # Thinking tokens are billed as output.
                self.total_output_tokens += (usage.candidates_token_count or 0) + (
                    usage.thoughts_token_count or 0
                )

        parsed = response.parsed
        if parsed is None:
            raise ValueError("The AI returned an unreadable answer.")
        return parsed.model_dump()

    def get_total_cost_usd(self):
        price_in, price_out = _pricing(self.model)
        return (self.total_input_tokens * price_in + self.total_output_tokens * price_out) / 1_000_000


def validate_api_key(api_key):
    """Returns None if the key works, otherwise a user-facing error message."""
    try:
        client = genai.Client(api_key=api_key)
        next(iter(client.models.list(config={"page_size": 1})), None)
        return None
    except Exception as e:
        return friendly_error(e)


def is_transient(e):
    if isinstance(e, errors.APIError):
        return e.code in (408, 429, 500, 502, 503, 504)
    # Network problems (timeouts, connection resets) and malformed answers are worth retrying.
    name = type(e).__name__.lower()
    return any(s in name for s in ("timeout", "connect", "network", "remoteprotocol")) or isinstance(e, ValueError)


def friendly_error(e):
    if isinstance(e, errors.APIError):
        if e.code in (400, 401, 403) and "api key" in str(e).lower():
            return "The Gemini API key is invalid. Click 'API key…' at the bottom of the window to update it."
        if e.code == 403:
            return "The Gemini API key doesn't have access. Click 'API key…' at the bottom of the window to update it."
        if e.code == 404:
            return "The AI model used by this version is no longer available. Please update the app."
        if e.code == 429:
            return "Gemini usage limit reached. Try again later or check the API key's billing."
        if e.code and e.code >= 500:
            return "Gemini is temporarily unavailable. Please try again."
        return e.message or str(e)
    name = type(e).__name__.lower()
    if "connect" in name or "timeout" in name:
        return "Couldn't reach Gemini. Check the internet connection."
    return str(e) or type(e).__name__
