"""When the app can't tell how a workbook is laid out, Gemini looks around it with a few small tools
and proposes the LAYOUT (header row + what each column is) for each sheet of documents.

It never returns values: the app reads every cell itself with that layout, the same way as when the
user maps it by hand, and the proposal is shown in the mapping screen to be confirmed. It only reads
a few rows at a time, so a workbook costs a cent or two at most.

    propose(api_key, path, model=None) -> {"layouts": {sheet: layout}, "skip": [sheets], "notes": str,
                                           "cost_usd": float, "steps": int}
"""
import json
import re

from google import genai
from google.genai import types
from openpyxl.utils import column_index_from_string, get_column_letter

from src.services import workbook

MAX_STEPS = 16
FIELD_HELP = {
    "supplier": "supplier written as 'NIF - name' in one column",
    "supplier_nif": "supplier's NIF only (9 digits)",
    "supplier_name": "supplier's name only",
    "number": "document number (may also contain the ATCUD after ' / ')",
    "atcud": "ATCUD or control code (separate column)",
    "date": "issue date",
    "type": "document type (Fatura, Fatura-recibo, Nota de crédito…)",
    "sector": "sector / activity",
    "status": "status / situation (Registado, Anulado…)",
    "total": "total amount (with VAT)",
    "vat": "VAT amount (IVA)",
    "base": "taxable base (without VAT)",
}

PROMPT = """You are helping a Portuguese accountant's app read his Excel workbook of e-Fatura purchase
documents ("Conferência EF"). Usually one sheet per year, one row per document, and a column where he
types a status code (a small number 1–8, or its description such as "DOC. OK").

Your job: for EVERY sheet that lists documents, find the header row and say which column holds each
field. Use the tools to look at the sheets (they show row numbers and column letters). Do not guess
from the sheet names alone: read rows.

Fields (map only the ones that exist; supplier/supplier_nif and total are required):
{fields}
- code: the column with his status code (if any)

Rules:
- Only map columns; never type values yourself.
- Before submitting, call try_layout for every sheet you map and check the result looks right
  (a sensible number of documents, totals that are amounts, dates that are dates, suppliers that are names/NIFs).
  If something looks wrong, look again and fix it.
- Sheets that are not lists of documents (settings, code lists, summaries, empty sheets) go in "skip".
- If a sheet's year isn't its name, give the year.
- Then call submit once with all sheets."""


class _Session:
    def __init__(self, path):
        self.path = path
        self.wb = workbook._open(path, data_only=True)
        self.values = {ws.title: [list(r) for r in ws.iter_rows(values_only=True)] for ws in self.wb.worksheets}
        self.submitted = None

    # ---- tools (called by the model) ----
    def list_sheets(self):
        """Lists the workbook's sheets with their size."""
        return {"sheets": [{"name": n, "rows": len(v), "columns": max((len(r) for r in v), default=0)}
                           for n, v in self.values.items()]}

    def read_rows(self, sheet: str, first_row: int, last_row: int):
        """Reads rows first_row..last_row (1-based, at most 30 rows) of a sheet, as 'row: A=… | B=…'."""
        rows = self.values.get(sheet)
        if rows is None:
            return {"error": f"No sheet named {sheet!r}."}
        first_row = max(1, int(first_row))
        last_row = min(len(rows), int(last_row), first_row + 29)
        out = []
        for n in range(first_row, last_row + 1):
            cells = [f"{get_column_letter(i + 1)}={workbook._show(c)}" for i, c in enumerate(rows[n - 1][:26])
                     if c not in (None, "")]
            out.append(f"{n}: " + (" | ".join(cells) if cells else "(empty)"))
        return {"sheet": sheet, "rows": out, "sheet_rows": len(rows)}

    def find_text(self, text: str):
        """Finds cells containing a text (case-insensitive), in all sheets. Up to 20 matches."""
        want = str(text).lower()
        hits = []
        for name, rows in self.values.items():
            for n, r in enumerate(rows, start=1):
                for i, c in enumerate(r):
                    if c is not None and want in str(c).lower():
                        hits.append(f"{name}!{get_column_letter(i + 1)}{n} = {workbook._show(c)}")
                        if len(hits) >= 20:
                            return {"matches": hits}
        return {"matches": hits}

    def try_layout(self, sheet: str, header_row: int, columns: str, code_column: str = "", year: int = 0):
        """Tries a layout and shows what would be imported. columns: 'field=LETTER, …' e.g.
        'date=A, supplier=B, number=C, total=D, vat=E'. code_column: a letter or ''."""
        try:
            layout = self._layout(header_row, columns, code_column, year)
        except ValueError as e:
            return {"error": str(e)}
        r = workbook.try_layout(self.path, sheet, layout)
        return {"documents": r["documents"], "with_code": r["coded"], "total": r["total"],
                "rows_without_total": r.get("skipped", 0), "first_documents": r["examples"],
                "notes": [n for n in r.get("notes", []) if "read correctly" not in n]}

    def submit(self, sheets: str):
        """Final answer. sheets: JSON list like
        [{"sheet": "2026", "header_row": 7, "columns": "supplier=B, number=C, date=E, total=F, vat=G",
          "code_column": "K", "year": 2026}, {"sheet": "Dados", "skip": true}]"""
        try:
            items = json.loads(sheets) if isinstance(sheets, str) else sheets
            layouts, skip = {}, []
            for it in items:
                if it.get("skip"):
                    skip.append(it["sheet"])
                else:
                    layouts[it["sheet"]] = self._layout(it["header_row"], it["columns"], it.get("code_column", ""),
                                                        it.get("year", 0))
        except (ValueError, KeyError, TypeError) as e:
            return {"error": f"Couldn't read the answer: {e}. Send it again."}
        self.submitted = {"layouts": layouts, "skip": skip}
        return {"ok": True}

    @staticmethod
    def _layout(header_row, columns, code_column, year):
        cols = {}
        for part in re.split(r"[,;]\s*", str(columns or "")):
            if not part.strip():
                continue
            field, _, letter = part.partition("=")
            field, letter = field.strip(), letter.strip().upper()
            if field not in FIELD_HELP:
                raise ValueError(f"Unknown field {field!r}. Use: {', '.join(FIELD_HELP)}.")
            if not re.fullmatch(r"[A-Z]{1,2}", letter):
                raise ValueError(f"{field}: {letter!r} is not a column letter.")
            cols[field] = column_index_from_string(letter) - 1
        if "total" not in cols or not ({"supplier", "supplier_nif"} & set(cols)):
            raise ValueError("A layout needs total and supplier (or supplier_nif).")
        code = str(code_column or "").strip().upper()
        return {"header_row": int(header_row), "cols": cols,
                "code_col": column_index_from_string(code) - 1 if re.fullmatch(r"[A-Z]{1,2}", code) else None,
                "year": int(year) if year else None, "number_has_atcud": False}


def _describe(name, args):
    """What the agent is doing, in words for the progress window."""
    if name == "list_sheets":
        return "Gemini is listing the sheets"
    if name == "read_rows":
        return f"Gemini is reading sheet {args.get('sheet')}, rows {args.get('first_row')}–{args.get('last_row')}"
    if name == "find_text":
        return f"Gemini is searching for “{args.get('text')}”"
    if name == "try_layout":
        return f"Gemini is trying a layout on sheet {args.get('sheet')}"
    if name == "submit":
        return "Gemini has a proposal"
    return f"Gemini: {name}"


def propose(api_key, path, model=None, progress=None):
    from src.services import models, settings
    from src.services.gemini_service import _pricing
    model = model or settings.load().get("model") or models.default_model()
    s = _Session(path)
    tools = [s.list_sheets, s.read_rows, s.find_text, s.try_layout, s.submit]
    by_name = {f.__name__: f for f in tools}
    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        tools=tools, automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        temperature=0.1,
        **({"thinking_config": types.ThinkingConfig(thinking_level="low")} if model.startswith("gemini-3") else {}))
    fields = "\n".join(f"- {k}: {v}" for k, v in FIELD_HELP.items())
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=PROMPT.format(fields=fields))])]
    tokens_in = tokens_out = steps = 0
    notes = ""
    say = progress or (lambda *a, **k: None)
    say("Gemini is looking at the workbook…", 0.1)
    while steps < MAX_STEPS and s.submitted is None:
        steps += 1
        resp = client.models.generate_content(model=model, contents=contents, config=config)
        u = resp.usage_metadata
        if u:
            tokens_in += u.prompt_token_count or 0
            tokens_out += (u.candidates_token_count or 0) + (u.thoughts_token_count or 0)
        cand = resp.candidates[0].content if resp.candidates else None
        if cand is None:
            break
        contents.append(cand)
        calls = resp.function_calls or []
        if not calls:
            notes = resp.text or ""
            contents.append(types.Content(role="user", parts=[types.Part.from_text(
                text="Please continue with the tools, and finish by calling submit.")]))
            continue
        replies = []
        for call in calls:
            say(_describe(call.name, call.args or {}), min(0.9, 0.1 + steps * 0.08))
            fn = by_name.get(call.name)
            try:
                result = fn(**(call.args or {})) if fn else {"error": f"No tool {call.name}"}
            except Exception as e:  # a bad argument from the model: tell it, let it retry
                result = {"error": str(e)}
            replies.append(types.Part.from_function_response(name=call.name, response={"result": result}))
        contents.append(types.Content(role="user", parts=replies))
    price_in, price_out = _pricing(model)
    cost = tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out
    out = s.submitted or {"layouts": {}, "skip": []}
    return {**out, "notes": notes, "cost_usd": round(cost, 5), "steps": steps, "model": model}
