"""Clicks through every screen with fake invoices and saves screenshots. For CI only:
it opens real windows, so don't run it on a computer someone is using.

Usage: python tools/ui_smoke.py <output_dir>
Exits 1 if any screen raised an error.
"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "ui-shots")
os.makedirs(OUT, exist_ok=True)
work = tempfile.mkdtemp(prefix="rjac-ui-")
os.environ["RJAC_DATA_DIR"] = os.path.join(work, "data")
os.environ.setdefault("GEMINI_API_KEY", "AIza-fake-key-for-ui-test")

import pymupdf  # noqa: E402

from src.services import history  # noqa: E402

inv = os.path.join(work, "Faturas Outubro")
os.makedirs(inv)
FAKE = [("Fatura FT A-29.pdf", {"date": "2026-10-06", "total_value": 60000.0, "invoice_number": "FT A/29",
                                 "supplier": "Quociente Invencível Lda"}),
        ("EDP outubro.pdf", {"date": "2026-10-14", "total_value": 84.12, "invoice_number": "FT 2026/88123",
                             "supplier": "EDP Comercial"}),
        ("scan_0001.pdf", {"date": "", "total_value": None, "invoice_number": "", "supplier": ""})]
FAKE += [(f"extra_{i:02d}.pdf", {"date": f"2026-09-{i + 1:02d}", "total_value": 10.0 + i,
                                  "invoice_number": f"FT X/{i}", "supplier": "Fornecedor Teste"}) for i in range(25)]
for name, values in FAKE:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 90), values["supplier"] or "Scanned page", fontsize=16)
    page.insert_text((72, 120), f"Fatura {values['invoice_number']}  Data {values['date']}", fontsize=11)
    page.insert_text((72, 700), f"Total {values['total_value'] or ''}", fontsize=13)
    path = os.path.join(inv, name)
    doc.save(path)
    doc.close()  # Windows can't delete/rename files that are still open
    history.save(history.fingerprint(path), values, "read", path, model="gemini-3.8-flash")

import shutil  # noqa: E402
shutil.copy(os.path.join(inv, "EDP outubro.pdf"), os.path.join(inv, "TESTE.pdf"))  # an exact copy

errors = []
import tkinter  # noqa: E402

tkinter.Tk.report_callback_exception = lambda self, *exc: errors.append(exc)
from tkinter import messagebox  # noqa: E402

messagebox.askyesno = messagebox.askokcancel = lambda *a, **k: True
dialogs = []
for _name in ("showwarning", "showinfo", "showerror"):  # never block on a popup: record it instead
    setattr(messagebox, _name, lambda *a, _n=_name, **k: dialogs.append((_n, a)))
from PIL import ImageGrab  # noqa: E402
import threading  # noqa: E402


def _watchdog():
    """If the UI hangs, save what's on screen and stop instead of waiting forever."""
    time.sleep(120)
    try:
        ImageGrab.grab(all_screens=True).save(os.path.join(OUT, "HANG.png"))
    except Exception:
        pass
    print("UI smoke test HUNG for 120s (see HANG.png). Popups seen:", dialogs, flush=True)
    os._exit(2)


threading.Thread(target=_watchdog, daemon=True).start()

from src.ui.main_window import MainWindow  # noqa: E402

app = MainWindow()
# keep the app's own fit-to-screen size


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.update()
        time.sleep(0.03)


def shot(name):
    pump(1.0)
    x, y, w, h = app.winfo_rootx(), app.winfo_rooty(), app.winfo_width(), app.winfo_height()
    try:
        ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(os.path.join(OUT, f"{name}.png"))
    except Exception as e:
        print(f"screenshot {name} failed: {e}")


try:
    from src.services import history as hist
    app.show_home(); shot("0_home")
    app.show_folder(inv); pump(2); shot("1_folder_before")
    app.show_review(inv); rv = app.screen
    t0 = time.time()
    while rv.in_flight and time.time() - t0 < 30:
        pump(0.2)
    shot("2_review")
    # Scrolling: the invoice list must move with the mouse wheel and (Tk 9) the trackpad
    canvas = rv.list._parent_canvas
    before = canvas.yview()
    rv.rows[3].text.event_generate("<MouseWheel>", delta=-120)
    pump(0.3)
    if canvas.yview()[0] <= before[0]:
        errors.append(f"mouse wheel did not scroll the invoice list: {before} -> {canvas.yview()}")
    else:
        print("mouse wheel scroll OK:", before, "->", canvas.yview())
    try:
        mid = canvas.yview()
        rv.rows[3].text.event_generate("<TouchpadScroll>", delta=(0 << 16) | ((-60) & 0xFFFF))
        pump(0.3)
        print("trackpad scroll:", mid, "->", canvas.yview())
        if canvas.yview()[0] <= mid[0]:
            errors.append("trackpad did not scroll the invoice list")
    except tkinter.TclError:
        print("trackpad event not supported by this Tk (8.6): trackpads send <MouseWheel> there")
    teste = os.path.join(inv, "TESTE.pdf")
    if teste not in rv.duplicate_of:
        errors.append(f"copy TESTE.pdf not flagged as duplicate: {rv.duplicate_of}")
    else:
        print("duplicate flagged:", "TESTE.pdf ->", rv.duplicate_of[teste])
        rv._goto(rv.files.index("TESTE.pdf")); shot("2c_review_duplicate")
    rv._goto(2); shot("2b_review_warning")
    rv.rename_all(); shot("3_rename_dialog")
    for w in app.winfo_children():
        if isinstance(w, tkinter.Toplevel):
            w.destroy()
    todo, done, skipped = rv._renamable()
    if "TESTE.pdf" in todo:
        errors.append("duplicate would be renamed")
    out_dir = os.path.join(work, "renamed")
    rv._do_rename(todo, done, skipped, out_dir, False); shot("4_done")   # keep originals, rename into another folder
    if not os.path.exists(teste):
        errors.append("duplicate was touched")
    print("files after rename:", sorted(os.listdir(inv))[:4], "...")
    app.screen.btn_export  # Done screen has an export button
    # Second review of the same folder: kept originals must not be renamed again
    app.show_review(inv); rv2 = app.screen
    t0 = time.time()
    while rv2.in_flight and time.time() - t0 < 30:
        pump(0.2)
    todo2 = rv2._renamable()[0]
    print("second run: elsewhere", len(rv2.copy_elsewhere), "| would rename", todo2)
    if todo2:
        errors.append(f"kept originals would be renamed again: {todo2}")
    rv2._goto(0); shot("4b_review_already_renamed")
    app.show_folder(inv); pump(2); shot("5_folder_after")
    runs = hist.runs(inv)
    print("runs recorded:", [(r["gemini_reads"], r["renamed"]) for r in runs])
    if not runs or runs[0]["renamed"] == 0:
        errors.append(f"run not recorded: {runs}")
    from src.services.excel_exporter import ExcelExporter
    from src.services import fields as fm
    import openpyxl
    xl = os.path.join(work, "out.xlsx")
    ExcelExporter.export(hist.query(folder=inv), [f for f in fm.load() if f.enabled and f.in_excel], xl)
    header = [c.value for c in openpyxl.load_workbook(xl).active[1]]
    print("excel columns:", header)
    if "Original name" not in header:
        errors.append("Original name missing from Excel")
    app.show_all(); shot("6_all_invoices")
    app.show_fields(); shot("7_fields")
    app.screen.e_sep.delete(0, "end"); app.screen.e_sep.insert(0, " / "); app.screen._sep_changed()
    shot("7b_fields_bad_separator")
    app.screen._reset_sep()
    app.show_settings(); shot("8_settings")
    # Night mode
    app.set_appearance("dark"); pump(1); shot("9_dark_settings")
    app.show_home(); shot("9_dark_home")
    app.show_folder(inv); pump(2); shot("9_dark_folder")
    app.show_review(inv); pump(3); shot("9_dark_review")
    app.set_appearance("system")
except Exception as e:
    errors.append(e)
app.destroy()

if dialogs:
    print("Popups shown during the test:", *dialogs, sep="\n")
if errors or any(d[0] in ("showwarning", "showerror") for d in dialogs):
    print("UI errors:", *errors, sep="\n")
    sys.exit(1)
print(f"UI smoke OK, screenshots in {OUT}")
