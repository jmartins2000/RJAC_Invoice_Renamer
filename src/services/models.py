"""Which Gemini models can be used, with prices and test results.

- Models: live from the Gemini API (whatever the key has access to).
- Current prices: live from LiteLLM's community-maintained price list (Google has no public
  pricing API usable with a Gemini key), cached on disk for offline use.
- Test results, scheduled price changes and models to hide: model_catalog.json, downloaded from
  GitHub so it can be updated without a new app version (bundled copy as fallback).
"""
import datetime
import json
import os
import re
import threading
from dataclasses import dataclass

import requests
from google import genai
from google.genai import types

from src.utils import get_resource_path
from src.version import GITHUB_REPO

CATALOG_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/model_catalog.json"
LIVE_PRICES_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
DEFAULT_TOKENS = (1100, 400)  # rough input/output tokens per invoice for untested models
EXCLUDE = re.compile(r"image|tts|embed|audio|live|veo|imagen|nano-banana|robotics|computer-use|learnlm|gemma|aqa")

_catalog = None
_live = None


def _on_ui_thread():
    return threading.current_thread() is threading.main_thread()


def warm():
    """Download catalog and prices in the background at startup (see main_window)."""
    threading.Thread(target=lambda: (catalog(), live_prices()), daemon=True).start()


def live_prices():
    """{model_id: (input, output)} USD per 1M tokens from LiteLLM; cached copy if offline."""
    global _live
    if _live is not None:
        return _live
    from src.services.settings import _dir
    cache = os.path.join(_dir(), "live_prices.json")
    if _on_ui_thread():  # never block the window on the network: use the disk cache for now
        try:
            with open(cache, encoding="utf-8") as f:
                return {k: tuple(v) for k, v in json.load(f).items()}
        except Exception:
            return {}
    data = None
    try:
        r = requests.get(LIVE_PRICES_URL, timeout=5)
        r.raise_for_status()
        raw = r.json()
        data = {k.split("/", 1)[1]: (v["input_cost_per_token"] * 1e6, v["output_cost_per_token"] * 1e6)
                for k, v in raw.items()
                if k.startswith("gemini/") and isinstance(v, dict)
                and v.get("input_cost_per_token") is not None and v.get("output_cost_per_token") is not None}
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        try:
            with open(cache, encoding="utf-8") as f:
                data = {k: tuple(v) for k, v in json.load(f).items()}
        except Exception:
            data = {}
    _live = data
    return _live


def catalog():
    """Remote catalog if reachable, else bundled. Cached for the session."""
    global _catalog
    if _catalog is None and _on_ui_thread():
        with open(get_resource_path(os.path.join("src", "data", "model_catalog.json")), encoding="utf-8") as f:
            return json.load(f)  # bundled copy; the background warm-up fetches the latest
    if _catalog is None:
        try:
            r = requests.get(CATALOG_URL, timeout=4)
            r.raise_for_status()
            _catalog = r.json()
        except Exception:
            with open(get_resource_path(os.path.join("src", "data", "model_catalog.json")), encoding="utf-8") as f:
                _catalog = json.load(f)
    return _catalog


def default_model():
    return catalog().get("default", "gemini-3.8-flash")


def price(model_id, on=None):
    """(input, output) USD per 1M tokens for a date, or None if unknown.
    Today's price comes from the live list; the catalog adds scheduled future changes."""
    today = datetime.date.today()
    on = on or today
    scheduled = catalog()["models"].get(model_id, {}).get("prices", [])
    if on == today or not scheduled:
        live = live_prices().get(model_id)
        if live:
            return live
    for p in scheduled:
        until = p.get("until")
        if until is None or on <= datetime.date.fromisoformat(until):
            return p["input"], p["output"]
    return None


def cost_per_invoice(model_id, on=None):
    p = price(model_id, on)
    if not p:
        return None
    tin, tout = catalog()["models"].get(model_id, {}).get("tokens_per_invoice", DEFAULT_TOKENS)
    return (tin * p[0] + tout * p[1]) / 1_000_000


def label(model_id):
    info = catalog()["models"].get(model_id, {})
    if info.get("label"):
        return info["label"]
    return model_id.replace("gemini-", "Gemini ").replace("-", " ").title().replace("Gemini", "Gemini")


@dataclass
class ModelInfo:
    id: str
    label: str
    tag: str
    cost: float | None       # USD per invoice today
    later: tuple | None      # (USD per invoice, date) when a price change is scheduled
    tested: str
    note: str


def describe(model_id):
    info = catalog()["models"].get(model_id, {})
    later = None
    prices = info.get("prices", [])
    if len(prices) > 1 and prices[0].get("until"):
        change = datetime.date.fromisoformat(prices[0]["until"]) + datetime.timedelta(days=1)
        if change > datetime.date.today():
            later = (cost_per_invoice(model_id, change), change)
    return ModelInfo(model_id, label(model_id), info.get("tag", ""), cost_per_invoice(model_id), later,
                     info.get("tested", ""), info.get("note", ""))


def available(api_key):
    """Models the key can use for this app, best first. Raises on network/API errors."""
    client = genai.Client(api_key=api_key)
    known = catalog()["models"]
    ids = []
    for m in client.models.list():
        mid = m.name.split("/")[-1]
        if not mid.startswith("gemini-") or EXCLUDE.search(mid):
            continue
        if "generateContent" not in (m.supported_actions or []):
            continue
        if known.get(mid, {}).get("hide"):
            continue
        ids.append(mid)
    default = default_model()
    infos = [describe(i) for i in dict.fromkeys(ids)]
    # Recommended first, then tested+priced by cost, then the rest alphabetically.
    infos.sort(key=lambda x: (x.id != default, x.cost is None, x.cost or 0, x.label))
    return infos


def probe(api_key, model_id):
    """Tiny structured request to check the model really works here. None if OK, else a message."""
    from src.services.gemini_service import friendly_error
    try:
        client = genai.Client(api_key=api_key)
        client.models.generate_content(
            model=model_id, contents="Return ok=true.",
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
                max_output_tokens=50))
        return None
    except Exception as e:
        return friendly_error(e)
