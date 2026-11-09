"""Read feedback sent from the app.

  python tools/feedback.py            list submissions
  python tools/feedback.py get ID     download + unzip into feedback_inbox/ID/
  python tools/feedback.py get new    download everything not downloaded yet
  python tools/feedback.py delete ID  remove it from the inbox (after you've downloaded it)

Uses the private admin token in ~/.config/rjac/feedback_admin_token (never in the repo).
New submissions can take up to a minute to show up in the list (Cloudflare KV).
"""
import io
import json
import os
import sys
import zipfile

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENDPOINT = os.environ.get("RJAC_FEEDBACK_URL", "https://rjac-feedback.rjac-invoices.workers.dev")
INBOX = os.path.join(ROOT, "feedback_inbox")


def token():
    path = os.path.expanduser("~/.config/rjac/feedback_admin_token")
    with open(path) as f:
        return f.read().strip()


def api(method, path, **kw):
    r = requests.request(method, f"{ENDPOINT}{path}", headers={"Authorization": f"Bearer {token()}"},
                         timeout=120, **kw)
    r.raise_for_status()
    return r


def listing():
    return api("GET", "/admin/list").json()


def get(sid, meta=None):
    meta = meta or next((m["meta"] for m in listing() if m["id"] == sid), None)
    if meta is None:
        sys.exit(f"No submission {sid}")
    data = b"".join(api("GET", f"/admin/{sid}/{n}").content for n in range(int(meta.get("parts", 1))))
    out = os.path.join(INBOX, sid)
    os.makedirs(out, exist_ok=True)
    zipfile.ZipFile(io.BytesIO(data)).extractall(out)
    print(f"{sid}: saved to {os.path.relpath(out, ROOT)}")


def main():
    args = sys.argv[1:]
    if not args:
        items = listing()
        if not items:
            print("No feedback yet.")
        for m in items:
            meta = m["meta"]
            got = "✓" if os.path.isdir(os.path.join(INBOX, m["id"])) else " "
            msg = (meta.get("message") or "").replace("\n", " ")
            print(f"{got} {m['id']}  {meta.get('kind', '?'):5s} {meta.get('bytes', 0) / 1e6:6.1f} MB  "
                  f"v{meta.get('app_version', '?')}  {meta.get('folder') or '-':20.20s}  {msg[:70]}")
    elif args[0] == "get" and len(args) == 2:
        if args[1] == "new":
            for m in listing():
                if not os.path.isdir(os.path.join(INBOX, m["id"])):
                    get(m["id"], m["meta"])
        else:
            get(args[1])
    elif args[0] == "delete" and len(args) == 2:
        print(api("DELETE", f"/admin/{args[1]}").json())
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
