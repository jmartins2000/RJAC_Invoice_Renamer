"""Serve the HTML interface to a normal (or headless) browser, backed by the real Python API.

For development and automated tests without opening the app window:
    python tools/web_dev.py [--port 8765] [--fake-gemini]
then open http://127.0.0.1:8765/ (or drive it with headless Chrome).

- `api.x(...)` calls from the page are POSTed to /api/x and run on the real `Api`.
- Pushes from Python (`_emit`) are kept in a list the page polls (/dev/events).
- File dialogs are answered from a queue: POST /dev/dialog with a JSON list of answers.
- --fake-gemini: no Gemini calls (no cost); files without a QR/history get made-up values.
Use RJAC_DATA_DIR to point at a throwaway data folder.
"""
import argparse
import json
import mimetypes
import os
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from src.webui.api import Api  # noqa: E402

WEB = os.path.join(ROOT, "src", "web")
SHIM = """
window.pywebview = { api: new Proxy({}, { get: (_, n) => async (...args) => {
  const r = await fetch('/api/' + n, { method: 'POST', body: JSON.stringify(args) });
  const j = await r.json();
  if (j.py_error) { console.error('Python error in ' + n + ':\\n' + j.py_error); throw new Error(j.py_error); }
  return j.result;
} }) };
let __seq = 0;
(async function poll() {
  for (;;) {
    try {
      const evs = await (await fetch('/dev/events?since=' + __seq)).json();
      for (const e of evs) { __seq = e.seq; window.dispatchEvent(new CustomEvent('py', { detail: { event: e.event, data: e.data } })); }
    } catch (e) {}
    await new Promise((r) => setTimeout(r, 120));
  }
})();
"""


class FakeWindow:
    def __init__(self):
        self.answers = []
        self.lock = threading.Lock()

    def create_file_dialog(self, *args, **kwargs):
        with self.lock:
            return self.answers.pop(0) if self.answers else None

    def evaluate_js(self, js):
        return None

    def destroy(self):
        pass


class DevApi(Api):
    def __init__(self):
        super().__init__()
        self._window = FakeWindow()
        self._events = []
        self._ev_lock = threading.Lock()

    def _emit(self, event, data=None):
        with self._ev_lock:
            self._events.append({"seq": len(self._events) + 1, "event": event,
                                 "data": json.loads(json.dumps(data, default=str))})


def fake_gemini():
    """Made-up readings instead of Gemini (keeps tests free and deterministic)."""
    import hashlib

    from src.services import gemini_service

    def call(self, pdf_bytes, mime="application/pdf"):  # only the network call is faked: QR checks still run
        n = int(hashlib.sha1(pdf_bytes[:4096]).hexdigest()[:6], 16)
        self.total_input_tokens += 2500
        self.total_output_tokens += 300
        return {"is_invoice": True, "date": f"2026-0{1 + n % 9}-{10 + n % 18}", "total_value": round(10 + n % 9000 / 100, 2),
                "invoice_number": f"FT T/{n % 1000}", "supplier": f"Supplier {n % 7}", "supplier_nif": ""}
    gemini_service.GeminiService._call = call


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--fake-gemini", action="store_true")
    args = ap.parse_args()
    if args.fake_gemini:
        fake_gemini()
    api = DevApi()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/dev/events":
                since = int(parse_qs(url.query).get("since", ["0"])[0])
                with api._ev_lock:
                    evs = [e for e in api._events if e["seq"] > since]
                return self._send(200, json.dumps(evs))
            if url.path == "/dev/shim.js":
                return self._send(200, SHIM, "text/javascript")
            rel = url.path.lstrip("/") or "index.html"
            path = os.path.normpath(os.path.join(WEB, rel))
            if not path.startswith(WEB) or not os.path.isfile(path):
                return self._send(404, "not found", "text/plain")
            with open(path, "rb") as f:
                data = f.read()
            if rel == "index.html":
                data = data.replace(b'<script type="module"', b'<script src="/dev/shim.js"></script>\n  <script type="module"')
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            if path.endswith((".js", ".mjs")):
                ctype = "text/javascript"
            self._send(200, data, ctype)

        def do_POST(self):
            url = urlparse(self.path)
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if url.path == "/dev/dialog":
                with api._window.lock:
                    api._window.answers = json.loads(body)
                return self._send(200, "{}")
            if url.path.startswith("/api/"):
                name = url.path[5:]
                fn = getattr(api, name, None)
                if name.startswith("_") or not callable(fn):
                    return self._send(404, json.dumps({"py_error": f"no method {name}"}))
                try:
                    result = fn(*json.loads(body or b"[]"))
                    return self._send(200, json.dumps({"result": result}, default=str))
                except Exception:
                    traceback.print_exc()
                    return self._send(200, json.dumps({"py_error": traceback.format_exc()}))
            self._send(404, "{}")

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Serving on http://127.0.0.1:{args.port}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
