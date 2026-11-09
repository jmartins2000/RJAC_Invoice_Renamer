"""Invoice data extraction with Gemini (google-genai SDK)."""
import os
import random
import threading
import time

from google import genai
from google.genai import errors, types
import json

# Chosen with tools/eval_extraction.py (18/18 on the sample set, Nov 2026).
DEFAULT_MODEL = "gemini-3.8-flash"

# Requests above this size are uploaded via the Files API instead of sent inline.
INLINE_LIMIT_BYTES = 18 * 1024 * 1024

MAX_ATTEMPTS = 5

def _pricing(model):
    """USD per 1M tokens (input, output) from the model catalog; conservative fallback if unknown."""
    from src.services import models
    return models.price(model) or (2.00, 10.00)


class GeminiService:
    """Extracts invoice fields from PDFs. Thread-safe; tracks token usage for cost display."""

    def __init__(self, api_key, model=None, field_defs=None):
        self.client = genai.Client(api_key=api_key)
        if not model:
            from src.services import models, settings
            model = os.environ.get("RJAC_MODEL") or settings.load().get("model") or models.default_model()
        self.model = model
        from src.services import fields as fieldmod
        self.fields = field_defs or fieldmod.load()
        self.schema = fieldmod.json_schema(self.fields)
        self.prompt = fieldmod.prompt(self.fields)
        self._lock = threading.Lock()
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def extract_invoice_data(self, file_path):
        """Returns a dict with the extracted fields, or {'error': message} on failure."""
        filename = os.path.basename(file_path)
        try:
            with open(file_path, "rb") as f:
                pdf_bytes = f.read()
            from src.services.file_types import mime_type
            data = self._call_with_retries(pdf_bytes, filename, mime_type(filename))
            self._apply_qr(file_path, data)
            if not data.get("is_invoice", True):
                data["warning"] = "This doesn't look like an invoice. Please check the values."
            print(f"[DONE] {filename}")
            return data
        except Exception as e:
            msg = friendly_error(e)
            print(f"[ERROR] {filename}: {msg}")
            return {"error": msg}

    def _apply_qr(self, file_path, data):
        """Use the official AT QR code (when present) as the source of truth for the values it holds."""
        from src.services import fields as fieldmod
        from src.services import qr_at
        qr = qr_at.read(file_path)
        if not qr:
            return
        enabled = {f.key: f for f in self.fields if f.enabled}
        corrected = []
        for key in ("date", "total_value", "invoice_number", "supplier_nif", "vat_amount"):
            if key not in enabled or qr.get(key) in (None, ""):
                continue
            old, new = data.get(key), qr[key]
            same = (abs(float(old) - float(new)) < 0.005 if isinstance(old, (int, float)) and isinstance(new, float)
                    else str(old or "").replace(" ", "").upper() == str(new).replace(" ", "").upper())
            if not same:
                f = enabled[key]
                if old not in (None, ""):
                    corrected.append(f"{f.label} {fieldmod.display_value(f, old)} → {fieldmod.display_value(f, new)}")
                data[key] = new
        data["is_invoice"] = True
        data["qr_checked"] = True
        if corrected:
            data["qr_corrected"] = corrected

    def _call_with_retries(self, pdf_bytes, filename, mime="application/pdf"):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return self._call(pdf_bytes, mime)
            except Exception as e:
                if attempt == MAX_ATTEMPTS or not is_transient(e):
                    raise
                wait = min(60, 2 ** attempt) + random.uniform(0, 1.5)
                print(f"[RETRY {attempt}] {filename}: {friendly_error(e)} — waiting {wait:.0f}s")
                time.sleep(wait)

    def _call(self, pdf_bytes, mime="application/pdf"):
        uploaded = None
        if len(pdf_bytes) <= INLINE_LIMIT_BYTES:
            pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type=mime)
        else:
            import io
            uploaded = self.client.files.upload(
                file=io.BytesIO(pdf_bytes), config={"mime_type": mime}
            )
            pdf_part = uploaded
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[pdf_part, self.prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=self.schema,
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

        try:
            data = json.loads(response.text or "")
        except ValueError:
            raise ValueError("The AI returned an unreadable answer.")
        if not isinstance(data, dict):
            raise ValueError("The AI returned an unreadable answer.")
        return data

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
            return "The Gemini API key is invalid. Open Settings to update it."
        if e.code == 403:
            return "The Gemini API key doesn't have access. Open Settings to update it."
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
