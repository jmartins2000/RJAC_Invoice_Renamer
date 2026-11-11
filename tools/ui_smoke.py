"""Clicks through every screen of the real app window with fake invoices and saves screenshots.
For CI only: it opens a real window, so don't run it on a computer someone is using.
(To try the screens locally without a window, use tools/web_dev.py with a headless browser.)

Usage: python tools/ui_smoke.py <output_dir>
Exits 1 if anything failed, 2 if the UI hung.
"""
import base64
import os
import shutil
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "ui-shots")
os.makedirs(OUT, exist_ok=True)
work = tempfile.mkdtemp(prefix="rjac-ui-")
os.environ["RJAC_DATA_DIR"] = os.path.join(work, "data")
os.environ.setdefault("GEMINI_API_KEY", "AIza-fake-key-for-ui-test")
os.environ["RJAC_FEEDBACK_URL"] = "http://127.0.0.1:9"  # never send test feedback; exercise the Desktop fallback

import pymupdf  # noqa: E402
from PIL import Image as _Img, ImageDraw as _Draw  # noqa: E402

from src.services import history  # noqa: E402

# ------------------------------------------------------------------ fake client folder
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

shutil.copy(os.path.join(inv, "EDP outubro.pdf"), os.path.join(inv, "TESTE.pdf"))  # an exact copy
_photo = _Img.new("RGB", (800, 1100), "white")
_Draw.Draw(_photo).text((60, 60), "Galp Energia  Fatura FT 9/2026  Total 41.80", fill="black")
_photo_path = os.path.join(inv, "foto fatura galp.png")
_photo.save(_photo_path)
history.save(history.fingerprint(_photo_path), {"date": "2026-10-20", "total_value": 41.8,
             "invoice_number": "FT 9/2026", "supplier": "Galp Energia"}, "read", _photo_path)

errors = []
# Every file-dialog filter must be one pywebview accepts (a bad one only fails when clicked)
import re as _re  # noqa: E402
from webview.util import parse_file_type  # noqa: E402
for _ft in _re.findall(r'"([^"]*\(\*[^"]*\))"', open(os.path.join(ROOT, "src", "webui", "api.py"), encoding="utf-8").read()):
    try:
        parse_file_type(_ft)
    except ValueError as _e:
        errors.append(f"bad file dialog filter: {_e}")
# Official AT QR code on a receipt image, remembered with a wrong year (from an old version)
import zxingcpp  # noqa: E402
from src.services import qr_at  # noqa: E402
_qr_text = ("A:500052999*B:516953648*C:PT*D:FS*E:N*F:20260606*G:FS 274062002/668058*H:JFNMG2WJ-668058"
            "*I1:PT*I7:40.65*I8:9.35*N:9.35*O:50.00*Q:FPEf*R:0177")
_qr_img = zxingcpp.write_barcode_to_image(zxingcpp.create_barcode(_qr_text, zxingcpp.BarcodeFormat.QRCode), scale=6)
_receipt = _Img.new("RGB", (900, 1500), "white")
_mv = memoryview(_qr_img)
_receipt.paste(_Img.frombytes("L", (_mv.shape[1], _mv.shape[0]), _mv.tobytes()).convert("RGB"), (250, 900))
_receipt_path = os.path.join(work, "qr_receipt.png")
_receipt.save(_receipt_path)
_qr = qr_at.read(_receipt_path)
print("AT QR read:", _qr)
if not _qr or _qr.get("date") != "2026-06-06" or _qr.get("total_value") != 50.0 or _qr.get("invoice_number") != "FS 274062002/668058":
    errors.append(f"AT QR not read correctly: {_qr}")
QR_FILE = "talao com qr.png"
shutil.copy(_receipt_path, os.path.join(inv, QR_FILE))
history.save(history.fingerprint(os.path.join(inv, QR_FILE)),
             {"date": "2024-06-06", "total_value": 50.0, "invoice_number": "FS 274062002/668058",
              "supplier": "Fuelgest24"}, "renamed", os.path.join(inv, QR_FILE))

# e-Fatura export for this client: two of its invoices + one with no receipt
EF_CSV = os.path.join(work, "efatura_export.csv")
with open(EF_CSV, "w", encoding="cp1252", newline="") as _f:
    _f.write("Data Emissão;NIF Emitente;Nome Emitente;Tipo;Nº Fatura;Valor Total\n"
             "06-10-2026;517875845;Quociente Invencível Lda;Fatura;FT A/29;60.000,00\n"
             "14-10-2026;503504564;EDP Comercial;Fatura;FT 2026/88123;84,12\n"
             "20-10-2026;500000009;Fornecedor Sem Talão;Fatura;FT ZZ/999;12,30\n")

from src.services import gemini_service  # noqa: E402

gemini_service.GeminiService._call = lambda self, *a, **k: {"is_invoice": True}  # never call Google in the test

# ------------------------------------------------------------------ the app window
import webview  # noqa: E402

from src.webui.app import create, start  # noqa: E402

api, window = create()
api.start_background = lambda: None  # no update check / model list from the network
OUT_DIR = os.path.join(work, "renamed")
os.makedirs(OUT_DIR)
api._ask_folder = lambda start=None: OUT_DIR                     # "Change" in the rename dialog
api._ask_save = lambda folder, name: os.path.join(work, name)    # every "Export to Excel"
window.create_file_dialog = lambda *a, **k: [EF_CSV]             # "Import export files…"


def watchdog():
    time.sleep(170)
    try:
        from PIL import ImageGrab
        ImageGrab.grab(all_screens=True).save(os.path.join(OUT, "HANG.png"))
    except Exception:
        pass
    print("UI smoke test HUNG (see HANG.png). Errors so far:", errors, flush=True)
    os._exit(2)


threading.Thread(target=watchdog, daemon=True).start()


def js(code):
    return window.evaluate_js(code)


def wait(cond, timeout=30, what=None):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if js(cond):
                return True
        except Exception:
            pass
        time.sleep(0.2)
    raise TimeoutError(f"waited {timeout}s for: {what or cond}")


def click(text, sel="button, .row, .file-row, .ef-item, .menu-item, .fchip, .link"):
    ok = js(f"""(() => {{ const el = [...document.querySelectorAll({sel!r})]
        .find((e) => e.textContent.trim().includes({text!r}) && !e.disabled);
        if (el) {{ el.click(); return true; }} return false; }})()""")
    if not ok:
        raise RuntimeError(f"nothing clickable with text {text!r} ({sel})")
    time.sleep(0.4)


def type_into(selector, value, index=0):
    js(f"""(() => {{ const el = document.querySelectorAll({selector!r})[{index}];
        el.value = {value!r}; el.dispatchEvent(new Event('input', {{ bubbles: true }})); }})()""")
    time.sleep(0.3)


def count(selector):
    return js(f"document.querySelectorAll({selector!r}).length")


def shot(name):
    time.sleep(0.6)
    js("window.__shotData = null; window.__rjacShot().then((d) => { window.__shotData = d; }, (e) => { window.__shotData = 'ERR ' + e; })")
    try:
        wait("!!window.__shotData", 20, "screenshot")
        data = js("window.__shotData")
        if data.startswith("ERR"):
            raise RuntimeError(data)
        with open(os.path.join(OUT, f"{name}.png"), "wb") as f:
            f.write(base64.b64decode(data.split(",", 1)[1]))
        print("shot", name, flush=True)
    except Exception as e:
        print(f"screenshot {name} failed: {e}", flush=True)


def os_shot(name):
    """A picture of the real window as the OS shows it (checks native rendering, fonts, DPI)."""
    try:
        from PIL import ImageGrab
        x, y, w, h = window.x, window.y, window.width, window.height
        ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(os.path.join(OUT, f"{name}.png"))
        print("os shot", name, flush=True)
    except Exception as e:
        print(f"OS screenshot {name} failed: {e}", flush=True)


def back():
    click("", ".topbar .btn.icon[title=Back]")


def check(cond, message):
    if not cond:
        errors.append(message)
        print("FAIL:", message, flush=True)


def test():
    try:
        try:
            wait("!!document.querySelector('.row, .empty')", 40, "home screen")
        except TimeoutError:
            print("PAGE STATE at timeout:", js("JSON.stringify({ready: document.readyState, url: location.href, "
                  "started: !!window.__rjacStarted, errors: window.__rjacErrors || 'no error log', "
                  "bridge: !!(window.pywebview && window.pywebview.api && typeof window.pywebview.api.app_info === 'function'), "
                  "app_children: (document.getElementById('app') || {children: []}).children.length})"))
            raise
        js("window.__errs = []; window.addEventListener('error', (e) => __errs.push(e.message));"
           "window.addEventListener('unhandledrejection', (e) => __errs.push(String(e.reason && (e.reason.message || e.reason))));")
        shot("0_home")
        os_shot("0_home_window")
        click("New client")
        wait("!!document.querySelector('.modal input')", 10, "new client dialog")
        shot("0b_new_client")
        click("Cancel", ".modal .btn")

        # --- Folder
        click("Faturas Outubro", ".row")
        wait("[...document.querySelectorAll('.topbar .btn.solid')].some((b) => !b.disabled)", 30, "folder button")
        shot("1_folder_before")

        # --- Review
        click("Review", ".topbar .btn.solid")
        wait("!!document.querySelector('.review') && !document.querySelector('.dot.reading')", 60, "all read")
        shot("2_review")
        s = api._session
        teste = os.path.join(inv, "TESTE.pdf")
        check(teste in s.duplicate_of, f"copy TESTE.pdf not flagged as duplicate: {s.duplicate_of}")
        check("foto fatura galp.png" in s.files, "image invoice not listed")
        qpath = os.path.join(inv, QR_FILE)
        print("history re-check via QR:", s.values.get(qpath, {}).get("date"), "| corrections:", s.qr.get(qpath))
        check(s.values.get(qpath, {}).get("date") == "2026-06-06", "wrong year from history not corrected by the QR")
        click(QR_FILE, ".file-row")
        wait("!!document.querySelector('.qr-box')", 30, "QR outline on the preview")
        shot("2e_review_qr_outline")
        click("Fatura FT A-29.pdf", ".file-row")
        wait("!!document.querySelector('.page-img img')", 30, "preview")
        js("document.querySelector('.zoom button:last-child').click(); document.querySelector('.zoom button:last-child').click()")
        time.sleep(0.4)
        zoom = js("document.querySelector('.zoom-pct').textContent")
        print("zoom:", zoom)
        check(zoom == "156%", f"preview zoom didn't change ({zoom})")
        shot("2d_review_zoom")
        click("TESTE.pdf", ".file-row")
        wait("!!document.querySelector('.notice')", 10, "duplicate notice")
        shot("2c_review_duplicate")
        click("scan_0001.pdf", ".file-row")
        wait("!!document.querySelector('.form, .notice')", 10, "warning file")
        shot("2b_review_warning")

        # --- Rename into another folder, keeping the originals
        click("Rename", ".topbar .btn.solid")
        wait("!!document.querySelector('.modal')", 10, "rename dialog")
        click("Change", ".modal .link")
        js("const t = document.querySelector('.modal .toggle.on'); if (t) t.click();")
        time.sleep(0.3)
        shot("3_rename_dialog")
        click("Rename", ".modal .btn.solid")
        wait("!!document.querySelector('.big-check')", 30, "done screen")
        shot("4_done")
        renamed = os.listdir(OUT_DIR)
        print("renamed:", len(renamed), "files, e.g.", sorted(renamed)[:2])
        check(any(f.endswith(".png") for f in renamed), "image invoice not renamed with its .png extension")
        check(os.path.exists(teste), "duplicate was touched")
        check(os.path.exists(os.path.join(inv, "EDP outubro.pdf")), "original deleted although 'delete' was off")
        click("Export to Excel")
        time.sleep(1.5)
        xl = os.path.join(work, "invoices.xlsx")
        check(os.path.exists(xl), "Excel export from the Done screen not saved")
        if os.path.exists(xl):
            import openpyxl
            header = [c.value for c in openpyxl.load_workbook(xl).active[1]]
            print("excel columns:", header)

        # --- Second review: kept originals must not be renamed again
        click("Back to")
        wait("[...document.querySelectorAll('.topbar .btn.solid')].some((b) => !b.disabled)", 30, "folder button")
        click("Review", ".topbar .btn.solid")
        wait("!!document.querySelector('.review') && !document.querySelector('.dot.reading')", 60, "second read")
        todo2 = api._session.renamable()[0]
        print("second run: elsewhere", len(api._session.copy_elsewhere), "| would rename", todo2)
        check(not todo2, f"kept originals would be renamed again: {todo2}")
        shot("4b_review_already_renamed")
        back()
        wait("!!document.querySelector('.folder-body .table')", 20, "folder table")
        shot("5_folder_after")
        runs = history.runs(inv)
        print("runs recorded:", [(r["gemini_reads"], r["renamed"]) for r in runs])
        check(runs and any(r["renamed"] for r in runs), f"run not recorded: {runs}")

        # --- Periods
        js("document.querySelector('.table-head .menu-btn').click()")
        time.sleep(0.3)
        click("Q3 2026", ".menu-item")
        time.sleep(1)
        rows = count(".folder-body tbody tr")
        print("Q3 2026 rows:", rows)
        check(rows == 25, f"Q3 2026 should show the 25 September invoices, got {rows}")
        shot("6_folder_q3")
        js("document.querySelector('.table-head .menu-btn').click()")
        time.sleep(0.3)
        click("Custom dates", ".menu-item")
        wait("!!document.querySelector('.modal input')", 10, "custom dates dialog")
        type_into(".modal input", "05/09/2026", 0)
        type_into(".modal input", "10.09.2026", 1)
        click("Show", ".modal .btn.solid")
        time.sleep(1)
        rows = count(".folder-body tbody tr")
        print("custom range rows:", rows)
        check(rows == 6, f"custom range should show 6 invoices, got {rows}")
        shot("6b_folder_custom_range")

        # --- e-Fatura
        click("Compare with e-Fatura")
        wait("!!document.querySelector('.center-col h1, .ef')", 20, "e-Fatura screen")
        shot("6c_efatura_empty")
        click("Import export files")
        wait("!!document.querySelector('.ef-item')", 20, "e-Fatura cases")
        view = api.efatura_view(inv)
        kinds = {k: sum(1 for i in view["items"] if i["kind"] == k) for k in ("matched", "differ", "missing", "not_in_ef")}
        print("e-Fatura comparison:", kinds)
        check(kinds["matched"] >= 2 and kinds["missing"] == 1, f"e-Fatura comparison wrong: {kinds}")
        shot("6d_efatura")
        click("No receipt", ".fchip")
        click("FT ZZ/999", ".ef-item")
        click("Choose a code", ".menu-btn")
        shot("6e_efatura_codes")
        click("3 ·", ".menu-item")
        time.sleep(1)
        from src.services import efatura
        check(3 in efatura.codes(inv).values(), "the chosen code (3) wasn't remembered")
        click("All", ".fchip")
        shot("6f_efatura_resolved")

        # --- Feedback: snip + send (fails on purpose) -> saved to the Desktop
        js("window.dispatchEvent(new Event('open-feedback'))")
        wait("!!document.querySelector('.modal textarea')", 10, "feedback dialog")
        type_into(".modal textarea", "UI test feedback")
        shot("7_feedback")
        click("Take screenshot")
        wait("!!document.querySelector('.snip')", 30, "snip overlay")
        shot("7b_snip")
        js("window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))")
        wait("!!document.querySelector('.shot img')", 10, "snippet attached")
        click("Send", ".modal .btn.solid")
        wait("/Desktop|saved/i.test(document.querySelector('.modal').textContent)", 60, "feedback fallback")
        shot("7c_feedback_saved")
        click("Close", ".modal .btn")

        # --- Settings, fields, night mode, small window
        back()
        wait("!!document.querySelector('.folder-body')", 20, "folder")
        back()
        wait("!!document.querySelector('.row')", 20, "home")
        click("Settings")
        wait("!!document.querySelector('section')", 20, "settings")
        shot("8_settings")
        click("Edit fields")
        wait("!!document.querySelector('.field-row')", 20, "fields")
        shot("8b_fields")
        type_into(".sep-input", " / ")
        check(count(".sep-input.bad") == 1, "a separator with / was accepted")
        shot("8c_fields_bad_separator")
        click("Reset", ".sep-top .link")
        back()
        wait("!!document.querySelector('section')", 20, "settings")
        click("Night", ".seg button")
        shot("9_dark_settings")
        os_shot("9_dark_settings_window")
        back()
        wait("!!document.querySelector('.row')", 20, "home")
        shot("9_dark_home")
        click("Faturas Outubro", ".row")
        wait("!!document.querySelector('.folder-body')", 20, "folder")
        shot("9_dark_folder")
        api.set_appearance("system")
        back()
        wait("!!document.querySelector('.row')", 20, "home")
        click("Settings")
        wait("!!document.querySelector('section')", 20, "settings")
        window.resize(1000, 560)
        time.sleep(1)
        scrollable = js("(() => { const p = document.querySelector('#app > .page'); return p.scrollHeight > p.clientHeight; })()")
        print("settings scrollable in a small window:", scrollable)
        check(scrollable, "Settings page not scrollable in a small window")
        js("document.querySelector('#app > .page').scrollTop = 10000")
        shot("9b_settings_small_window_scrolled")

        js_errors = js("window.__errs") or []
        if js_errors:
            print("Page errors:", *js_errors, sep="\n  ")
            errors.extend(f"page error: {e}" for e in js_errors)
    except Exception as e:
        import traceback
        traceback.print_exc()
        errors.append(repr(e))
        shot("ZZ_failure")
    finally:
        window.destroy()


start(test)

if errors:
    print("UI errors:", *errors, sep="\n")
    sys.exit(1)
print(f"UI smoke OK, screenshots in {OUT}")
