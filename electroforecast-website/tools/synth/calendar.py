from __future__ import annotations

from datetime import date, timedelta


def easter(year: int) -> date:
    """Western Easter Sunday (anonymous Gregorian algorithm, Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    lw = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lw) // 451
    month, day = divmod(h + lw - 7 * m + 114, 31)
    return date(year, month, day + 1)


def holidays(year: int, cfg) -> set[date]:
    """Fixed holidays from cfg, plus Maundy Thursday and Good Friday if cfg.holy_week."""
    out = set()
    for md in cfg.fixed_holidays:
        mm, dd = md.split("-")
        out.add(date(year, int(mm), int(dd)))
    if cfg.holy_week:
        e = easter(year)
        out.add(e - timedelta(days=3))
        out.add(e - timedelta(days=2))
    return out
