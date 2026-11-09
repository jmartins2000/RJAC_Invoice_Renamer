"""Measure extraction accuracy against samples/ground_truth.json.

Usage: python tools/eval_extraction.py [--model gemini-2.5-pro] [--legacy]
  --legacy  runs the original v1 extraction code (from git history) for a baseline.
Needs GEMINI_API_KEY in the environment or a .env file.
"""
import argparse, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SAMPLES = os.path.join(ROOT, "samples")


def norm_id(s):
    return re.sub(r"[\s]", "", str(s or "")).upper()


def score(expected, got):
    """Returns dict field -> bool."""
    if "error" in got:
        return {f: False for f in ("date", "total_value", "invoice_number", "supplier")}
    if expected.get("is_invoice") is False:
        empty = not any([got.get("date"), got.get("total_value"), got.get("invoice_number"), got.get("supplier")])
        return {"not_invoice_detected": got.get("is_invoice") is False or empty, "no_invented_values": empty}
    try:
        value_ok = abs(float(got.get("total_value") or 0) - expected["total_value"]) < 0.01
    except (TypeError, ValueError):
        value_ok = False
    return {
        "date": got.get("date") == expected["date"],
        "total_value": value_ok,
        "invoice_number": norm_id(got.get("invoice_number")) in {norm_id(x) for x in expected["invoice_number"]},
        "supplier": any(k in str(got.get("supplier", "")).lower() for k in expected["supplier"]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model")
    ap.add_argument("--legacy", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--update-catalog", action="store_true",
                    help="write the score and measured tokens for this model into model_catalog.json")
    args = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    key = os.environ["GEMINI_API_KEY"]

    if args.legacy:
        import importlib.util, subprocess, tempfile
        src = subprocess.check_output(["git", "-C", ROOT, "show", "5812520:src/services/gemini_service.py"], text=True)
        path = os.path.join(tempfile.mkdtemp(), "legacy_gemini.py")
        open(path, "w").write(src)
        spec = importlib.util.spec_from_file_location("legacy_gemini", path)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        svc = mod.GeminiService()
        label = "v1 (gemini-2.5-pro, original prompt)"
    else:
        from src.services.gemini_service import GeminiService
        svc = GeminiService(key, model=args.model)
        label = f"v2 ({svc.model})"

    truth = {k: v for k, v in json.load(open(os.path.join(SAMPLES, "ground_truth.json"))).items() if not k.startswith("_")}
    t0 = time.time()
    with ThreadPoolExecutor(args.workers) as ex:
        results = dict(zip(truth, ex.map(lambda f: svc.extract_invoice_data(os.path.join(SAMPLES, f)), truth)))

    totals, hits, failures = {}, {}, []
    for f, exp in truth.items():
        s = score(exp, results[f] if results[f] is not None else {"error": "none"})
        for field, ok in s.items():
            totals[field] = totals.get(field, 0) + 1
            hits[field] = hits.get(field, 0) + ok
        bad = [k for k, ok in s.items() if not ok]
        if bad:
            failures.append((f, bad, results[f]))

    print(f"\n=== {label}: {len(truth)} files, {time.time()-t0:.0f}s, tokens in={svc.total_input_tokens} out={svc.total_output_tokens} ===")
    for field in totals:
        print(f"  {field:22s} {hits[field]}/{totals[field]}")
    all_ok = sum(1 for f in truth if f not in {x[0] for x in failures})
    print(f"  {'files fully correct':22s} {all_ok}/{len(truth)}")
    for f, bad, got in failures:
        print(f"  ✗ {f}: wrong {bad} -> {got}")

    if args.update_catalog and not args.legacy:
        n = len(truth)
        for path in (os.path.join(ROOT, "model_catalog.json"), os.path.join(ROOT, "src", "data", "model_catalog.json")):
            cat = json.load(open(path, encoding="utf-8"))
            entry = cat["models"].setdefault(svc.model, {})
            entry["tested"] = f"{all_ok}/{n}"
            entry["tokens_per_invoice"] = [round(svc.total_input_tokens / n), round(svc.total_output_tokens / n)]
            json.dump(cat, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        print(f"  catalog updated for {svc.model} (push to main so installed apps see it)")


if __name__ == "__main__":
    main()
