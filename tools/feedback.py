"""Read feedback sent from the app.

  python tools/feedback.py            list submissions
  python tools/feedback.py get ID     download + unzip into feedback_inbox/ID/
  python tools/feedback.py get new    download everything not downloaded yet
  python tools/feedback.py delete ID  remove it from the inbox (after you've downloaded it)
  python tools/feedback.py harvest ID add its QR-verified receipts (and any e-Fatura export files)
                                      to the private test dataset
                                      (samples/ = github.com/jmartins2000/RJAC-test-data) and push

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


def harvest(sid):
    """Copy every receipt whose official AT QR is readable into the test dataset, with the QR values as truth."""
    import hashlib
    import shutil
    import subprocess
    sys.path.insert(0, ROOT)
    from src.services import qr_at
    pkg = os.path.join(INBOX, sid, "folder", "files")
    if not os.path.isdir(pkg):
        get(sid)
    if not os.path.isdir(pkg):
        sys.exit("This feedback has no folder files.")
    samples = os.path.join(ROOT, "samples")
    gt_path = os.path.join(samples, "ground_truth.json")
    gt = json.load(open(gt_path, encoding="utf-8"))
    sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()  # noqa: E731
    have = set()
    for dirpath, _, names in os.walk(samples):
        if ".git" in dirpath:
            continue
        have.update(sha(os.path.join(dirpath, n)) for n in names if not n.endswith((".json", ".md")))
    dest_rel = f"uncle-feedback-{sid[:8]}"
    dest = os.path.join(samples, dest_rel)
    os.makedirs(dest, exist_ok=True)
    n = len([x for x in os.listdir(dest) if not x.startswith(".")])
    added = skipped = 0
    for f in sorted(os.listdir(pkg)):
        src = os.path.join(pkg, f)
        if sha(src) in have:
            skipped += 1
            continue
        q = qr_at.read(src)
        if not q:
            continue
        n += 1
        name = f"r{n:02d}{os.path.splitext(f)[1].lower()}"
        shutil.copy(src, os.path.join(dest, name))
        gt[f"{dest_rel}/{name}"] = {"date": q["date"], "total_value": q["total_value"],
                                    "invoice_number": [q["invoice_number"]], "supplier": [""]}
        have.add(sha(src))
        added += 1
    json.dump(gt, open(gt_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"{sid}: added {added} QR-verified receipts, {skipped} already in the dataset")
    # Real e-Fatura export files: kept for testing the parser against real column layouts
    exports = os.path.join(INBOX, sid, "folder", "efatura", "exports")
    if os.path.isdir(exports):
        ef_dest = os.path.join(samples, "efatura-exports", sid)
        os.makedirs(ef_dest, exist_ok=True)
        for f in os.listdir(exports):
            if sha(os.path.join(exports, f)) not in have:
                shutil.copy(os.path.join(exports, f), os.path.join(ef_dest, f))
                added += 1
        print(f"kept {len(os.listdir(ef_dest))} e-Fatura export file(s) in samples/efatura-exports/{sid}")
    if added:
        subprocess.run(["git", "-C", samples, "add", "-A"], check=True)
        subprocess.run(["git", "-C", samples, "commit", "-qm", f"Harvest {added} QR-verified receipts from feedback {sid}"],
                       check=True)
        subprocess.run(["git", "-C", samples, "push", "-q"], check=True)
        print("dataset pushed to the private repo")


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
    elif args[0] == "harvest" and len(args) == 2:
        harvest(args[1])
    elif args[0] == "delete" and len(args) == 2:
        print(api("DELETE", f"/admin/{args[1]}").json())
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
