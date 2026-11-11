"""Measures the layout agent on the made-up example workbooks (tools/workbook_examples.py).

  python tools/eval_layout_agent.py [--only renamed_columns.xlsx] [--model gemini-3.8-flash]

For each example: the agent proposes a layout, the app reads the workbook with it, and the result
(documents, codes, total per sheet) is compared with the known answer. Costs a few cents in total.
Needs GEMINI_API_KEY in the environment or .env.
"""
import argparse
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--model")
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    key = os.environ["GEMINI_API_KEY"]
    os.environ.setdefault("RJAC_DATA_DIR", tempfile.mkdtemp(prefix="rjac-eval-"))
    import workbook_examples
    from src.services import layout_agent, workbook

    out = tempfile.mkdtemp(prefix="rjac-wbx-")
    expected = workbook_examples.write_all(out)
    total_cost, good = 0.0, 0
    names = [n for n in expected if not args.only or n == args.only]
    for name in names:
        e = expected[name]
        path = os.path.join(out, name)
        t = time.time()
        try:
            r = layout_agent.propose(key, path, model=args.model)
            data = workbook.read(path, overrides=r["layouts"], skip=set(r["skip"]))
            got = {s["sheet"].replace("Purchases ", ""): {
                "documents": len(s["documents"]), "coded": sum(1 for x in s["documents"] if x["code"]),
                "total": round(sum(x["doc"]["total"] for x in s["documents"]), 2)} for s in data["sheets"]}
            ok = got == e["sheets"]
            total_cost += r["cost_usd"]
            detail = f"{r['steps']} steps · ${r['cost_usd']:.4f} · {time.time() - t:.0f}s"
        except Exception as ex:  # noqa: BLE001
            ok, got, detail = False, {"error": str(ex)[:200]}, ""
        good += ok
        print(f"{'✓' if ok else '✗'} {name:22} ({e['what']}) {detail}")
        if not ok:
            print(f"     got      {got}\n     expected {e['sheets']}")
    print(f"\n{good}/{len(names)} correct · total cost ${total_cost:.4f}")


if __name__ == "__main__":
    main()
