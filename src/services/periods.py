"""Invoice-date periods (quarters and years) for filtering one client's invoices."""
import datetime


def quarter_bounds(year, q):
    start = datetime.date(year, 3 * (q - 1) + 1, 1)
    end = datetime.date(year + (q == 4), 1 if q == 4 else 3 * q + 1, 1) - datetime.timedelta(days=1)
    return start.isoformat(), end.isoformat()


CUSTOM = "Custom dates…"


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


def nice(iso):
    d = datetime.date.fromisoformat(iso)
    return f"{d.day} {d.strftime('%b')} {d.year}"


def options(years):
    """[(label, (start, end), short)] for a client: shortcuts first, then each year and its quarters."""
    today = datetime.date.today()
    q = (today.month - 1) // 3 + 1
    lq_year, lq = (today.year, q - 1) if q > 1 else (today.year - 1, 4)
    opts = [("All dates", (None, None), ""),
            (CUSTOM, (None, None), ""),
            (f"This quarter (Q{q} {today.year})", quarter_bounds(today.year, q), f"Q{q} {today.year}"),
            (f"Last quarter (Q{lq} {lq_year})", quarter_bounds(lq_year, lq), f"Q{lq} {lq_year}"),
            (f"This year ({today.year})", (f"{today.year}-01-01", f"{today.year}-12-31"), str(today.year)),
            (f"Last year ({today.year - 1})", (f"{today.year - 1}-01-01", f"{today.year - 1}-12-31"),
             str(today.year - 1))]
    for y in sorted({int(y) for y in years}, reverse=True):
        opts.append((f"{y} (whole year)", (f"{y}-01-01", f"{y}-12-31"), str(y)))
        for qq in (4, 3, 2, 1):
            opts.append((f"Q{qq} {y}", quarter_bounds(y, qq), f"Q{qq} {y}"))
    seen, out = set(), []
    for label, rng, short in opts:
        if label not in seen:
            seen.add(label)
            out.append((label, rng, short))
    return out
