"""Made-up "Conferência EF" workbooks in different shapes, each with the answer it should give.

  python tools/workbook_examples.py OUT_DIR      writes the .xlsx files + expected.json

Used by tools/test_efatura.py (automatic reading) and later to measure the layout agent. No real client
data: suppliers, numbers and amounts are invented.

Each example: name, what's awkward about it, whether the automatic reader is expected to get it,
and the expected result per year sheet (documents, codes, total).
"""
import datetime
import json
import os
import random
import sys

import openpyxl

CODES = ["DOC. OK", "EM ANÁLISE", "SEM DOC. Contabilizado. Aguarda 1ª / 2ª via", "SEM DOC. Não Contabilizado",
         "NÃO ELEGÍVEL", "PESQUISAR E IMPRIMIR", "IMPRIMIR EF", "Standby"]
SUPPLIERS = [("500000001", "Livraria Exemplo Lda"), ("500000002", "Restaurante Teste Lda"),
             ("500000003", "Combustíveis Ficção SA"), ("500000004", "Telecom Inventada SA"),
             ("500000005", "Papelaria Modelo Unipessoal Lda")]
TYPES = ["Fatura", "Fatura-recibo", "Fatura simplificada"]


def _docs(year, n, seed):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        nif, name = SUPPLIERS[i % len(SUPPLIERS)]
        d = datetime.datetime(year, 1 + (i * 11) // n, 1 + (i * 7) % 27)
        total = round(rnd.uniform(3, 900), 2)
        vat = round(total - total / 1.23, 2)
        out.append({"nif": nif, "name": name, "number": f"FT A{year % 100}/{100 + i}", "atcud": f"JFAB{seed:02d}CD-{100 + i}",
                    "type": TYPES[i % 3], "date": d, "total": total, "vat": vat, "base": round(total - vat, 2),
                    "code": (i % 4) + 1 if i % 5 else None})
    return sorted(out, key=lambda x: x["date"])


def _dados(wb, client="CLIENTE EXEMPLO, LDA", nif="509999999"):
    ws = wb.create_sheet("Dados")
    ws.append(["Designação:", client, 1, CODES[0]])
    ws.append(["NIF:", nif, 2, CODES[1]])
    for i, label in enumerate(CODES[2:], start=3):
        ws.append([None, None, i, label])


def new_layout(path, years=(2025, 2026), header_row=7, codes_as_text=False, junk_rows=False, reorder=False):
    """Like his sheets from 2023 on: title rows, header on row 7, 'Nº FATURA / ATCUD' together, code in K."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    expected = {}
    cols = ["SETOR", "EMITENTE", "Nº FATURA\nATCUD", "TIPO", "DATA\nEMISSÃO", "TOTAL", "IVA", "BASE\nTRIBUTÁVEL",
            "SITUAÇÃO", "COM.\nEMITENTE", "INSERIR\nCÒD.", "DESCRITIVO CHECK", "MÊS"]
    order = list(range(len(cols)))
    if reorder:
        order = [1, 2, 4, 5, 6, 7, 3, 0, 8, 9, 10, 11, 12]  # supplier first, sector moved
    for y in years:
        ws = wb.create_sheet(str(y))
        ws["A1"] = "MAPA DE CONTROLO DOS DOCUMENTOS E-FATURA"
        ws["A3"], ws["B3"] = "NOME:", "CLIENTE EXEMPLO, LDA"
        ws["A4"], ws["B4"] = "NIF:", "509999999"
        for j, ci in enumerate(order):
            ws.cell(row=header_row, column=j + 1, value=cols[ci])
        docs = _docs(y, 40, y)
        r = header_row + 2
        for k, d in enumerate(docs):
            if junk_rows and k == 20:
                r += 2  # two blank rows
                ws.cell(row=r, column=order.index(1) + 1, value=None)
                ws.cell(row=r, column=order.index(5) + 1, value="=SUM(F1:F2)")  # a stray total line
                r += 1
            code = d["code"]
            if codes_as_text and code:
                code = CODES[code - 1]
            values = [None, f"{d['nif']} - {d['name']}", f"{d['number']} / {d['atcud']}", d["type"], d["date"],
                      d["total"], d["vat"], d["base"], "Registado", None, code, None, None]
            for j, ci in enumerate(order):
                ws.cell(row=r, column=j + 1, value=values[ci])
            r += 1
        expected[str(y)] = {"documents": len(docs), "coded": sum(1 for d in docs if d["code"]),
                            "total": round(sum(d["total"] for d in docs), 2)}
    _dados(wb)
    wb.save(path)
    return expected


def old_layout(path, years=(2018,)):
    """Like his 2017–2022 sheets: header on row 4, number and control code apart, code in column L."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    expected = {}
    for y in years:
        ws = wb.create_sheet(str(y))
        ws["B2"], ws["C2"], ws["D2"], ws["E2"] = "DESIGNAÇÃO:", "CLIENTE EXEMPLO, LDA", "ANO", y
        ws.append([])
        ws.append([None, "Setor", "Comerciante", "Tipo", "Situação", "Nº Fatura", "Código Controlo", "Data Emissão",
                   "IVA", "Valor Total", "Registado por Comerciante", "CÒD.", "Descritivo"])
        ws.append([])
        docs = _docs(y, 30, y + 1)
        for d in docs:
            ws.append([d["date"].month, "Outros", f"{d['nif']} - {d['name']}", d["type"], "Registada", d["number"],
                       "t9HL", d["date"], d["vat"], d["total"], None, d["code"], None])
        expected[str(y)] = {"documents": len(docs), "coded": sum(1 for d in docs if d["code"]),
                            "total": round(sum(d["total"] for d in docs), 2)}
    _dados(wb)
    wb.save(path)
    return expected


def split_supplier(path, year=2026):
    """NIF and name in separate columns, no code column at all."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = str(year)
    ws.append(["Data", "NIF Emitente", "Nome Emitente", "Nº Documento", "ATCUD", "Tipo", "Valor Total", "Valor IVA"])
    docs = _docs(year, 25, 7)
    for d in docs:
        ws.append([d["date"], d["nif"], d["name"], d["number"], d["atcud"], d["type"], d["total"], d["vat"]])
    wb.save(path)
    return {str(year): {"documents": len(docs), "coded": 0, "total": round(sum(d["total"] for d in docs), 2)}}


def renamed_columns(path, year=2026):
    """Column names the keyword rules don't know: needs the agent (or the user) to map them."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = str(year)
    ws.append(["Quando", "Quem (contribuinte)", "Doc.", "Montante c/ imposto", "Imposto", "Estado do doc", "Marca"])
    docs = _docs(year, 20, 9)
    for d in docs:
        ws.append([d["date"], f"{d['nif']} - {d['name']}", d["number"], d["total"], d["vat"], "Registado", d["code"]])
    wb.save(path)
    return {str(year): {"documents": len(docs), "coded": sum(1 for d in docs if d["code"]),
                        "total": round(sum(d["total"] for d in docs), 2)}}


def english(path, year=2026):
    """Headers in English."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Purchases " + str(year)
    ws.append(["Issue date", "Vendor tax ID", "Vendor", "Invoice no.", "Amount", "Tax", "Status code"])
    docs = _docs(year, 15, 11)
    for d in docs:
        ws.append([d["date"], d["nif"], d["name"], d["number"], d["total"], d["vat"], d["code"]])
    wb.save(path)
    return {str(year): {"documents": len(docs), "coded": sum(1 for d in docs if d["code"]),
                        "total": round(sum(d["total"] for d in docs), 2)}}


EXAMPLES = [
    ("new_layout.xlsx", "his layout from 2023 on", True, lambda p: new_layout(p)),
    ("old_layout.xlsx", "his layout from 2017–2022", True, lambda p: old_layout(p)),
    ("header_lower.xlsx", "header on row 12 instead of 7", True, lambda p: new_layout(p, years=(2026,), header_row=12)),
    ("reordered.xlsx", "columns in another order", True, lambda p: new_layout(p, years=(2026,), reorder=True)),
    ("codes_as_text.xlsx", "codes written as their description", True, lambda p: new_layout(p, years=(2026,), codes_as_text=True)),
    ("junk_rows.xlsx", "blank rows and a stray total line in the middle", True, lambda p: new_layout(p, years=(2026,), junk_rows=True)),
    ("split_supplier.xlsx", "NIF and name in separate columns, no code column", True, split_supplier),
    ("renamed_columns.xlsx", "column names the rules don't know", False, renamed_columns),
    ("english.xlsx", "headers in English", False, english),
]


def write_all(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    expected = {}
    for name, what, auto, make in EXAMPLES:
        expected[name] = {"what": what, "automatic": auto, "sheets": make(os.path.join(out_dir, name))}
    with open(os.path.join(out_dir, "expected.json"), "w", encoding="utf-8") as f:
        json.dump(expected, f, ensure_ascii=False, indent=2)
    return expected


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "workbook_examples"
    write_all(out)
    print(f"Wrote {len(EXAMPLES)} example workbooks to {out}")
