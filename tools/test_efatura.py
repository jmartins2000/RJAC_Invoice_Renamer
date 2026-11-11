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

print("\nPart 3 — status codes, cancelled documents, Excel in the accountant's layout")
from openpyxl import load_workbook  # noqa: E402
from src.webui.api import Api  # noqa: E402
c3 = os.path.join(WORK, "Cliente Codigos")
os.makedirs(c3)
history.add_project(c3)
recibo = os.path.join(c3, "recibo.pdf")
open(recibo, "wb").write(b"%PDF-1.4 test")
history.save(history.fingerprint(recibo), {"date": "2026-01-05", "total_value": 50.0, "invoice_number": "FT A/1",
             "supplier": "Livraria", "_nif": "500000001"}, "confirmed", recibo, project=c3)
exp3 = write("export_codes.csv",
             "Setor;Emitente;Nº Fatura / ATCUD;Tipo;Data Emissão;Total;IVA;Base Tributável;Situação\n"
             "Outros;500000001 - Livraria Exemplo Lda;FT A/1 / JFAB12CD-1;Fatura;05-01-2026;50,00;9,35;40,65;Registado\n"
             "Outros;500000002 - Sem Recibo Lda;FT B/2 / JFAB12CD-2;Fatura;20-01-2026;100,00;18,70;81,30;Registado\n"
             "Outros;500000003 - Anulada Lda;FT C/3 / JFAB12CD-3;Fatura;21-01-2026;500,00;0;500,00;"
             "Documento Anulado pelo Emitente\n"
             "Outros;500000004 - Credito SA;NC D/4 / JFAB12CD-4;Nota de crédito;03-02-2026;10,00;1,87;8,13;Registado\n")
efatura.import_files(c3, [exp3])
api = Api()
view = api.efatura_view(c3)
kinds = {i["ef"]["nif"] if i["ef"] else "receipt": i for i in view["items"]}
check(kinds["500000003"]["kind"] == "cancelled", "cancelled document is its own case, not 'no receipt'")
check(kinds["500000001"]["kind"] == "matched" and kinds["500000001"]["code"] == 1 and kinds["500000001"]["code_auto"],
      "matched document gets code 1 automatically")
check(kinds["500000002"]["code"] is None, "document without receipt has no code yet")
api.efatura_set_code(c3, kinds["500000002"]["id"], 3)
api.efatura_set_code(c3, kinds["500000001"]["id"], 2)
view = api.efatura_view(c3)
kinds = {i["ef"]["nif"]: i for i in view["items"] if i["ef"]}
check(kinds["500000002"]["code"] == 3 and not kinds["500000002"]["code_auto"], "chosen code is kept")
check(kinds["500000001"]["code"] == 2, "automatic code can be changed")
api.efatura_set_code(c3, kinds["500000001"]["id"], None)
back = {i["ef"]["nif"]: i for i in api.efatura_view(c3)["items"] if i["ef"]}["500000001"]
check(back["code"] == 1 and back["code_auto"], "removing a chosen code goes back to the automatic one")
months = efatura.monthly_totals(efatura.rows(c3))
check([m["month"] for m in months] == ["2026-01", "2026-02"], "monthly totals per month")
check(months[0]["count"] == 2 and abs(months[0]["total"] - 150) < 0.001, "cancelled document left out of the totals")
check(abs(months[1]["total"] + 10) < 0.001, "credit note subtracts")
out_xlsx = os.path.join(WORK, "out.xlsx")
api._ask_save = lambda *a, **k: out_xlsx
check(api.efatura_export(c3) is True, "export runs")
wb = load_workbook(out_xlsx)
ws = wb["Conferência"]
head = [c.value for c in ws[1]]
check(head[:13] == ["SETOR", "EMITENTE", "Nº FATURA / ATCUD", "TIPO", "DATA EMISSÃO", "TOTAL", "IVA",
                    "BASE TRIBUTÁVEL", "SITUAÇÃO", "COM. EMITENTE", "INSERIR CÓD.", "DESCRITIVO CHECK", "MÊS"],
      "first sheet has the accountant's columns")
data = {r[1]: r for r in ws.iter_rows(min_row=2, values_only=True)}
check(len(data) == 4, f"one row per e-Fatura document (got {len(data)})")
r2 = data["500000002 - Sem Recibo Lda"]
check(r2[2] == "FT B/2 / JFAB12CD-2" and r2[10] == 3 and r2[11].startswith("SEM DOC. Contabilizado") and r2[12] == 1,
      "number with ATCUD, code number + description, month")
r1 = data["500000001 - Livraria Exemplo Lda"]
check(r1[10] == 1 and r1[13] == "recibo.pdf", "matched row: code 1 and the receipt's file")
check(ws.cell(row=2, column=1).fill.start_color.rgb.endswith("00B050") or
      any(ws.cell(row=i, column=1).fill.start_color.rgb.endswith("00B050") for i in range(2, 6)),
      "code 1 rows coloured green like his workbook")
check("Totais mensais" in wb.sheetnames, "monthly totals sheet")

print("\nPart 4 — clients: name, move to another folder, delete")
api.rename_client(c3, "Cliente Códigos, Lda", "513 215 204")
p3 = history.project(c3)
check(p3["name"] == "Cliente Códigos, Lda" and p3["nif"] == "513215204", "name and NIF saved (NIF digits only)")
moved = os.path.join(WORK, "Pasta Nova")
os.makedirs(moved)
history.move_project(c3, moved)
efatura.move_project(c3, moved)
check(history.project(c3) is None and history.project(moved)["name"] == "Cliente Códigos, Lda", "client moved with its name")
check(len(history.query(folder=moved)) == 1, "its invoices moved")
check(efatura.stored_count(moved) == 4 and 3 in efatura.codes(moved).values(), "its e-Fatura rows and codes moved")
other = os.path.join(WORK, "Outro")
os.makedirs(other)
history.add_project(other)
try:
    history.move_project(moved, other)
    check(False, "moving onto another client's folder is refused")
except ValueError:
    check(True, "moving onto another client's folder is refused")
api.delete_client(moved)
check(history.project(moved) is None and efatura.stored_count(moved) == 0 and not efatura.codes(moved),
      "deleting a client removes all its data")
check(os.path.isdir(moved), "deleting a client leaves its folder alone")

print("\nPart 5 — the accountant's workbook (made-up examples)")
sys.path.insert(0, os.path.join(ROOT, "tools"))
import workbook_examples  # noqa: E402
from src.services import workbook  # noqa: E402
wbx = os.path.join(WORK, "wbx")
expected = workbook_examples.write_all(wbx)
for name, e in expected.items():
    try:
        d = workbook.read(os.path.join(wbx, name))
        got = {s["sheet"].replace("Purchases ", ""): {"documents": len(s["documents"]),
               "coded": sum(1 for x in s["documents"] if x["code"]),
               "total": round(sum(x["doc"]["total"] for x in s["documents"]), 2)} for s in d["sheets"]}
    except Exception as ex:  # noqa: BLE001
        got = {"error": str(ex)}
    if e["automatic"]:
        check(got == e["sheets"], f"{name}: {e['what']} → read correctly")
    else:
        check(got != e["sheets"], f"{name}: {e['what']} → not guessed (left for the agent / the user)")
c5 = os.path.join(WORK, "Cliente Workbook")
os.makedirs(c5)
history.add_project(c5)
r5 = workbook.import_workbook(c5, os.path.join(wbx, "new_layout.xlsx"))
check(r5["documents"] == 80 and r5["client_nif"] == "509999999", "import: documents and client NIF from the workbook")
check(len(workbook.codes_for(c5)) == 8 and workbook.codes_for(c5)[0]["label"] == "DOC. OK", "the client's code list comes from 'Dados'")
same = workbook.export_workbook(c5, os.path.join(WORK, "same.xlsx"))
check(same["added"] == 0 and same["codes_changed"] == 0, "nothing new → nothing added or changed")
newq = write("newq.csv", "Setor;Emitente;Nº Fatura / ATCUD;Tipo;Data Emissão;Total;IVA;Base Tributável;Situação\n"
             "Outros;500000009 - Novo Fornecedor Lda;FT N/1 / JFNN11AA-1;Fatura;20-12-2026;61,50;11,50;50,00;Registado\n"
             "Outros;500000009 - Novo Fornecedor Lda;FT N/2 / JFNN11AA-2;Fatura;05-01-2027;24,60;4,60;20,00;Registado\n")
efatura.import_files(c5, [newq])
key = efatura.row_key(efatura.parse(newq)[0])
efatura.set_code(c5, key, 2)
out5 = workbook.export_workbook(c5, os.path.join(WORK, "updated.xlsx"))
check(out5["added"] == 2 and out5["new_sheets"] == ["2027"], f"new quarter: 2 added, sheet 2027 created ({out5})")
again = workbook.read(out5["path"])
counts = {s["sheet"]: len(s["documents"]) for s in again["sheets"]}
check(counts == {"2025": 40, "2026": 41, "2027": 1}, f"written workbook reads back with the new documents ({counts})")
n1 = [d for s in again["sheets"] if s["sheet"] == "2026" for d in s["documents"] if d["doc"]["number"] == "FT N/1"]
check(len(n1) == 1 and n1[0]["code"] == 2 and n1[0]["doc"]["atcud"] == "JFNN11AA-1",
      "the new document is written with its ATCUD and its code")

c6 = os.path.join(WORK, "Cliente Mapeado")
os.makedirs(c6)
history.add_project(c6)
odd = os.path.join(wbx, "renamed_columns.xlsx")
pv = {x["sheet"]: x for x in workbook.preview(odd, c6)}
check(pv["2026"]["looks_like_data"] and not pv["2026"]["layout"], "unknown layout: offered for mapping by hand")
manual = {"header_row": 1, "cols": {"date": 0, "supplier": 1, "number": 2, "total": 3, "vat": 4, "status": 5},
          "code_col": 6}
t = workbook.try_layout(odd, "2026", manual)
want = expected["renamed_columns.xlsx"]["sheets"]["2026"]
check((t["documents"], t["coded"], t["total"]) == (want["documents"], want["coded"], want["total"]),
      f"mapping by hand gives the right result ({t['documents']} docs, {t['total']})")
workbook.import_workbook(c6, odd, data=workbook.read(odd, overrides={"2026": manual}))
pv2 = {x["sheet"]: x for x in workbook.preview(odd, c6)}
check(bool(pv2["2026"]["layout"]), "the mapping is remembered for this client")
again6 = workbook.read(odd, saved=workbook.saved_layouts(c6))
check(len(again6["sheets"][0]["documents"]) == want["documents"], "next import of the same workbook needs no help")

shutil.rmtree(WORK, ignore_errors=True)
print("\nALL OK" if not failures else f"\n{len(failures)} FAILED")
sys.exit(1 if failures else 0)
