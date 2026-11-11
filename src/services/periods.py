"""Invoice-date periods (quarters and years) for filtering one client's invoices."""
import datetime


def quarter_bounds(year, q):
    start = datetime.date(year, 3 * (q - 1) + 1, 1)
    end = datetime.date(year + (q == 4), 1 if q == 4 else 3 * q + 1, 1) - datetime.timedelta(days=1)
    return start.isoformat(), end.isoformat()


CUSTOM = "Custom dates…"  # shown translated; the screens use the period's "kind" to recognise it


def parse_date(text):
    """'01/02/2026', '1.2.2026', '2026-02-01', '01-02-2026' → '2026-02-01' (day first), or None."""
    import re
    t = (text or "").strip()
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", t)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", t)
        if not m:
            return None
        d, mo, y = map(int, m.groups())
        y += 2000 if y < 100 else 0
    try:
        return datetime.date(y, mo, d).isoformat()
    except ValueError:
        return None


MONTHS_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def nice(iso):
    from src.services.i18n import lang
    d = datetime.date.fromisoformat(iso)
    month = MONTHS_PT[d.month - 1] if lang() == "pt" else d.strftime("%b")
    return f"{d.day} {month} {d.year}"


def custom_label():
    from src.services.i18n import tr
    return tr(CUSTOM)


def options(years):
    """[(label, (start, end), short, kind)] for a client: shortcuts first, then each year and its quarters.
    Labels are in the user's language; kind (all, custom, this_quarter, …) is for the code."""
    from src.services.i18n import tr
    today = datetime.date.today()
    q = (today.month - 1) // 3 + 1
    lq_year, lq = (today.year, q - 1) if q > 1 else (today.year - 1, 4)
    T = "T" if __import__("src.services.i18n", fromlist=["lang"]).lang() == "pt" else "Q"  # trimestre / quarter
    opts = [(tr("All dates"), (None, None), "", "all"),
            (tr(CUSTOM), (None, None), "", "custom"),
            (tr("This quarter ({q})", q=f"{T}{q} {today.year}"), quarter_bounds(today.year, q), f"{T}{q} {today.year}", "this_quarter"),
            (tr("Last quarter ({q})", q=f"{T}{lq} {lq_year}"), quarter_bounds(lq_year, lq), f"{T}{lq} {lq_year}", "last_quarter"),
            (tr("This year ({y})", y=today.year), (f"{today.year}-01-01", f"{today.year}-12-31"), str(today.year), "this_year"),
            (tr("Last year ({y})", y=today.year - 1), (f"{today.year - 1}-01-01", f"{today.year - 1}-12-31"),
             str(today.year - 1), "last_year")]
    for y in sorted({int(y) for y in years}, reverse=True):
        opts.append((tr("{y} (whole year)", y=y), (f"{y}-01-01", f"{y}-12-31"), str(y), "year"))
        for qq in (4, 3, 2, 1):
            opts.append((f"{T}{qq} {y}", quarter_bounds(y, qq), f"{T}{qq} {y}", "quarter"))
    seen, out = set(), []
    for label, rng, short, kind in opts:
        if label not in seen:
            seen.add(label)
            out.append((label, rng, short, kind))
    return out
