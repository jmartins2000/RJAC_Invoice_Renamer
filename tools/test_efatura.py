"""Tests for the e-Fatura import and comparison (no window, no network).

  python tools/test_efatura.py

Part 1 parses generated exports in the formats reported for the portal.
Part 2 uses the private test dataset's QR-verified receipts (samples/, if present): it builds a
client history from them, a matching e-Fatura export with planted differences, and checks that
the comparison finds exactly those.
"""
import glob
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
WORK = tempfile.mkdtemp(prefix="rjac-efatura-")
os.environ["RJAC_DATA_DIR"] = os.path.join(WORK, "data")

from src.services import efatura, history, qr_at  # noqa: E402

failures = []


def check(cond, msg):
    print(("  ✓ " if cond else "  ✗ ") + msg)
    if not cond:
        failures.append(msg)


def write(name, text, encoding="utf-8"):
    path = os.path.join(WORK, name)
    with open(path, "w", encoding=encoding, newline="") as f:
        f.write(text)
    return path


print("Part 1 — export formats")
a = write("separate_columns.csv",
          "Data Emissão;NIF Emitente;Nome Emitente;Tipo;Nº Fatura;ATCUD;Setor de Atividade;Situação;"
          "Base Tributável;Valor IVA;Valor Total\n"
          "15-01-2026;500000001;Livraria Exemplo Lda;Fatura;FT A/12;JFAB12CD-12;Outros;Registada;40,65;9,35;50,00\n"
          "30-04-2026;500000005;Energia Exemplo SA;Fatura;FT 2026/991;JFZZ99XY-991;Eletricidade;Registada;"
          "1.016,26;233,74;1.250,00\n"
          "02-04-2026;500000003;Telecom Exemplo SA;Nota de Crédito;NC 1/7;JFCC11AA-7;Comunicações;Registada;"
          "35,77;8,23;44,00\n")
rows = efatura.parse(a)
check(len(rows) == 3, "separate NIF/name columns: 3 rows")
check(rows[1]["total"] == 1250.0 and rows[1]["base"] == 1016.26, "Portuguese numbers (1.016,26 → 1016.26)")
check(rows[0]["date"] == "2026-01-15", "DD-MM-YYYY dates")
check(rows[2]["credit_note"] and rows[2]["total"] == 44.0, "credit note detected, amount positive")
check(rows[0]["number"] == "FT A/12" and rows[0]["atcud"] == "JFAB12CD-12", "number and ATCUD columns")

b = write("merged_columns_cp1252.csv",
          "Faturas - Adquirente - 1.º trimestre 2026\n\n"
          "Setor;Emitente;Tipo;Situação;Nº Fatura / ATCUD;Data Emissão;Total;IVA;Base Tributável\n"
          "Outros;500000001 - Livraria Exemplo Lda;Fatura-Recibo;Pendente;FR 3/45 / JFQQ12RR-45;"
          "03-02-2026;123,00;23,00;100,00\n", encoding="cp1252")
rows = efatura.parse(b)
check(len(rows) == 1, "title line before the header, cp1252 encoding")
check(rows[0]["supplier_nif"] == "500000001" and rows[0]["supplier_name"] == "Livraria Exemplo Lda",
      "merged 'NIF - Name' column split")
check(rows[0]["number"] == "FR 3/45" and rows[0]["atcud"] == "JFQQ12RR-45", "merged 'number / ATCUD' split")

try:
    efatura.parse(write("not_an_export.csv", "a;b;c\n1;2;3\n"))
    check(False, "a random CSV is rejected")
except ValueError:
    check(True, "a random CSV is rejected")

project = os.path.join(WORK, "Cliente Teste")
os.makedirs(project)
history.add_project(project)
n1, total1 = efatura.import_files(project, [a])
n2, total2 = efatura.import_files(project, [a, b])  # overlapping files
check(total1 == 3 and total2 == 4, f"duplicates across files ignored ({total1} → {total2})")

print("\nPart 2 — comparison on real QR-verified receipts")
receipts = sorted(glob.glob(os.path.join(ROOT, "samples", "uncle-feedback-*", "*")))
if not receipts:
    receipts = sorted(glob.glob(os.path.join(os.path.dirname(ROOT), "samples", "uncle-feedback-*", "*")))
if not receipts:
    receipts = sorted(glob.glob("/Users/joaomartins/Documents/General/RJAC/samples/uncle-feedback-*/*"))
if not receipts:
    print("  (skipped: private test dataset not available)")
else:
    client = os.path.join(WORK, "Cliente Real")
    os.makedirs(client)
    history.add_project(client)
    qrs = []
    for f in receipts:
        q = qr_at.read(f)
        if not q:
            continue
        dest = os.path.join(client, os.path.basename(f))
        shutil.copy(f, dest)
        qrs.append((dest, q))
    # The client's processed invoices = values from each receipt's QR (as the app stores them)
    for dest, q in qrs:
        v = {"date": q["date"], "total_value": q["total_value"], "invoice_number": q["invoice_number"],
             "supplier": "x", "_nif": q["supplier_nif"]}
        history.save(history.fingerprint(dest), v, "confirmed", dest, project=client)
    # One invoice processed without QR/NIF and without a number → should still match as "probable"
    probable_path, probable_q = qrs[0]
    history.save(history.fingerprint(probable_path), {"date": probable_q["date"],
                 "total_value": probable_q["total_value"], "invoice_number": "", "supplier": "x"},
                 "confirmed", probable_path, project=client, force=True)
    # e-Fatura export: every receipt except 3 (→ not in e-Fatura), one wrong total (→ differ),
    # plus 2 invoices that have no receipt (→ missing)
    not_reported = qrs[-3:]
    wrong_total = qrs[1]
    lines = ["Data Emissão;NIF Emitente;Nome Emitente;Tipo;Nº Fatura;Valor Total"]
    for dest, q in qrs[:-3]:
        total = q["total_value"] + (5 if (dest, q) == wrong_total else 0)
        lines.append(f"{q['date'][8:]}-{q['date'][5:7]}-{q['date'][:4]};{q['supplier_nif']};Fornecedor;Fatura;"
                     f"{q['invoice_number']};{str(f'{total:.2f}').replace('.', ',')}")
    lines.append("10-05-2026;509999999;Sem Talão Lda;Fatura;FT X/1;12,30")
    lines.append("11-05-2026;509999998;Outro Sem Talão;Fatura;FT X/2;45,60")
    export = write("export_real.csv", "\n".join(lines) + "\n", encoding="cp1252")
    efatura.import_files(client, [export])
    res = efatura.compare(client)
    n = len(qrs)
    print(f"  {n} receipts; e-Fatura has {n - 3 + 2} rows")
    check(len(res["not_in_ef"]) == 3, f"3 receipts not in e-Fatura (got {len(res['not_in_ef'])})")
    check(len(res["missing"]) == 2, f"2 e-Fatura invoices without receipt (got {len(res['missing'])})")
    check(len(res["differ"]) == 1 and "total" in res["differ"][0][2][0],
          f"1 invoice with a different total (got {len(res['differ'])})")
    probable = [m for m in res["matched"] if m[2] == "probable"]
    check(len(probable) == 1, f"1 invoice matched as 'probable' by NIF/date/total (got {len(probable)})")
    check(len(res["matched"]) == n - 3 - 1, f"{n - 4} matched in total (got {len(res['matched'])})")

shutil.rmtree(WORK, ignore_errors=True)
print("\nALL OK" if not failures else f"\n{len(failures)} FAILED")
sys.exit(1 if failures else 0)
