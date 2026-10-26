"""Small iCalendar (.ics) reader: VEVENTs, time zones, RRULE/EXDATE and moved instances."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import rruleset, rrulestr

from .common import TZ

WINDOWS_TZ = {
    "central standard time": "America/Chicago",
    "eastern standard time": "America/New_York",
    "mountain standard time": "America/Denver",
    "pacific standard time": "America/Los_Angeles",
}


def _unfold(text: str) -> list[str]:
    return re.sub(r"\r?\n[ \t]", "", text).splitlines()


def _split(line: str) -> tuple[str, dict, str]:
    in_q = False
    for i, ch in enumerate(line):
        if ch == '"':
            in_q = not in_q
        elif ch == ":" and not in_q:
            head, value = line[:i], line[i + 1:]
            break
    else:
        return line.upper(), {}, ""
    parts = re.findall(r'(?:[^;"]|"[^"]*")+', head)
    name = parts[0].upper()
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.upper()] = v.strip('"')
    return name, params, value


def _unescape(v: str) -> str:
    return v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip()


def _zone(tzid: str | None):
    if not tzid:
        return TZ
    tzid = tzid.strip().strip("/")
    try:
        return ZoneInfo(tzid)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(WINDOWS_TZ.get(tzid.lower(), "America/Chicago"))


def parse_dt(value: str, params: dict) -> tuple[datetime, bool]:
    """Return an aware datetime in Madison time and whether it is an all-day date."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        d = datetime.strptime(value[:8], "%Y%m%d")
        return d.replace(tzinfo=TZ), True
    utc = value.endswith("Z")
    d = datetime.strptime(value.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
    if utc:
        return d.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ), False
    return d.replace(tzinfo=_zone(params.get("TZID"))).astimezone(TZ), False


def _fix_until(rule: str) -> str:
    """dateutil needs UNTIL in UTC when DTSTART is time-zone aware."""
    def rep(m):
        v = m.group(1)
        if v.endswith("Z"):
            return m.group(0)
        if len(v) == 8:
            return f"UNTIL={v}T235959Z"
        return f"UNTIL={v}Z"
    return re.sub(r"UNTIL=([0-9TZ]+)", rep, rule)


def parse_ics(text: str, start: datetime, end: datetime) -> list[dict]:
    """All event instances that overlap [start, end)."""
    blocks, cur = [], None
    for line in _unfold(text):
        if line.upper() == "BEGIN:VEVENT":
            cur = []
        elif line.upper() == "END:VEVENT":
            if cur is not None:
                blocks.append(cur)
            cur = None
        elif cur is not None and line:
            cur.append(_split(line))

    masters, overrides = [], {}
    for props in blocks:
        ev = {"rrule": [], "rdate": [], "exdate": []}
        for name, params, value in props:
            try:
                if name in ("DTSTART", "DTEND"):
                    ev[name.lower()], ev[name.lower() + "_allday"] = parse_dt(value, params)
                elif name == "DURATION":
                    ev["duration"] = _duration(value)
                elif name == "RRULE":
                    ev["rrule"].append(value)
                elif name in ("EXDATE", "RDATE"):
                    for v in value.split(","):
                        ev[name.lower()].append(parse_dt(v, params)[0])
                elif name == "RECURRENCE-ID":
                    ev["recurrence_id"] = parse_dt(value, params)[0]
                elif name in ("SUMMARY", "DESCRIPTION", "LOCATION", "URL", "UID", "STATUS"):
                    ev[name.lower()] = _unescape(value)
            except (ValueError, TypeError):
                continue
        if "dtstart" not in ev or ev.get("status", "").upper() == "CANCELLED" and "recurrence_id" not in ev:
            continue
        if "recurrence_id" in ev:
            overrides[(ev.get("uid"), ev["recurrence_id"])] = ev
        else:
            masters.append(ev)

    out = []

    def emit(ev, s):
        if ev.get("status", "").upper() == "CANCELLED":
            return
        allday = ev.get("dtstart_allday", False)
        if "dtend" in ev:
            dur = ev["dtend"] - ev["dtstart"]
        else:
            dur = ev.get("duration") or (timedelta(days=1) if allday else timedelta(0))
        e = s + dur
        if (e if dur else s + timedelta(minutes=1)) <= start or s >= end:
            return
        out.append({
            "title": ev.get("summary", "").strip(),
            "start": s, "end": e if dur else None, "allday": allday,
            "description": ev.get("description", ""), "location": ev.get("location", ""),
            "url": ev.get("url", ""), "uid": ev.get("uid", ""),
        })

    for ev in masters:
        if ev["rrule"] or ev["rdate"]:
            rs = rruleset()
            for r in ev["rrule"]:
                try:
                    rs.rrule(rrulestr(_fix_until(r), dtstart=ev["dtstart"]))
                except (ValueError, TypeError):
                    pass
            for d in ev["rdate"]:
                rs.rdate(d)
            for d in ev["exdate"]:
                rs.exdate(d)
            look_back = timedelta(days=2)
            for s in rs.between(start - look_back, end, inc=True):
                if (ev.get("uid"), s) in overrides:
                    continue
                emit(ev, s)
        else:
            emit(ev, ev["dtstart"])
    for (uid, _), ev in overrides.items():
        emit(ev, ev["dtstart"])
    return out


def _duration(v: str) -> timedelta:
    m = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", v.strip())
    if not m:
        return timedelta(0)
    sign = -1 if m.group(1) == "-" else 1
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    return sign * timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)
