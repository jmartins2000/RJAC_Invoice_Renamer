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
    app.show_setup(); shot("1_setup")
    app.show_review(inv, inv); rv = app.screen
    t = time.time()
    while rv.in_flight and time.time() - t < 30:
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
    rv._goto(2); shot("2b_review_warning")
    rv.rename_all(); shot("3_rename_dialog")
    for w in app.winfo_children():
        if isinstance(w, tkinter.Toplevel):
            w.destroy()
    todo, done, skipped = rv._renamable()
    rv._do_rename(todo, done, skipped, inv, True); shot("4_done")
    app.show_history(); shot("5_history")
    app.show_fields(); shot("6_fields")
    app.screen.e_sep.delete(0, "end"); app.screen.e_sep.insert(0, " / "); app.screen._sep_changed()
    shot("6b_fields_bad_separator")
    app.screen._reset_sep()
    app.show_settings(); shot("7_settings")
    print("files after rename:", sorted(os.listdir(inv)))
except Exception as e:
    errors.append(e)
app.destroy()

if dialogs:
    print("Popups shown during the test:", *dialogs, sep="\n")
if errors or any(d[0] in ("showwarning", "showerror") for d in dialogs):
    print("UI errors:", *errors, sep="\n")
    sys.exit(1)
print(f"UI smoke OK, screenshots in {OUT}")
