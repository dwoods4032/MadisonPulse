"""Read OpenStreetMap opening_hours ("Mo-Th 11:00-22:00; Fr,Sa 11:00-02:00; Su off").

Returns the format the site uses: [[days], "HH:MM", "HH:MM"] with days 0 = Monday,
and a closing time after midnight written past 24:00 ("26:00" = 2 am).
Anything it can't read returns None, which the site treats as "hours unknown".
"""
from __future__ import annotations

import re

DAYS = {"mo": 0, "tu": 1, "we": 2, "th": 3, "fr": 4, "sa": 5, "su": 6}
TIME = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\+?$")


def _days(spec: str) -> list[int] | None:
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip().lower()
        if re.fullmatch(r"[a-z]{2}-[a-z]{2}", part):
            a, b = DAYS.get(part[:2]), DAYS.get(part[3:])
            if a is None or b is None:
                return None
            d = a
            while True:
                out.append(d)
                if d == b:
                    break
                d = (d + 1) % 7
        elif part in DAYS:
            out.append(DAYS[part])
        else:
            return None
    return out


def _times(spec: str) -> list[tuple[int, int]] | None:
    out = []
    for part in spec.split(","):
        m = TIME.match(part.strip())
        if not m:
            return None
        o = int(m.group(1)) * 60 + int(m.group(2))
        c = int(m.group(3)) * 60 + int(m.group(4))
        if c <= o:
            c += 24 * 60  # closes after midnight
        out.append((o, c))
    return out


def parse(raw: str | None):
    if not raw:
        return None
    raw = raw.strip()
    if raw == "24/7":
        return [[list(range(7)), "00:00", "24:00"]]
    week: dict[int, list[tuple[int, int]]] = {}
    for rule in raw.split(";"):
        rule = re.sub(r"\s+", " ", rule.strip())
        if not rule or rule.lower().startswith("ph"):
            continue
        rule = re.sub(r",\s*ph\b", "", rule, flags=re.I)
        if re.fullmatch(r"[\d:,\- +]+", rule):  # times only: every day
            days, times = list(range(7)), _times(rule.replace(" ", ""))
        else:
            m = re.match(r"^([A-Za-z,\- ]+?)\s+(off|closed|[\d:,\-+ ]+)$", rule)
            if not m:
                return None
            days = _days(m.group(1).replace(" ", ""))
            times = [] if m.group(2).lower() in ("off", "closed") else _times(m.group(2).replace(" ", ""))
        if days is None or times is None:
            return None
        for d in days:
            week[d] = times  # later rules override earlier ones
    if not week:
        return None
    # group days that share the same span (first open to last close)
    groups: dict[tuple[int, int], list[int]] = {}
    for d, times in sorted(week.items()):
        if times:
            span = (min(t[0] for t in times), max(t[1] for t in times))
            groups.setdefault(span, []).append(d)
    fmt = lambda m: f"{m // 60:02d}:{m % 60:02d}"
    return [[days, fmt(o), fmt(c)] for (o, c), days in groups.items()]
