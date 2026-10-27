"""Find and read event data on a venue's website.

Each venue site is checked once for the sources it offers (an .ics feed, a Google
Calendar embed, the WordPress "The Events Calendar" API, a Squarespace events
page, schema.org Event data). Later runs go straight to those sources.
"""
from __future__ import annotations

import html as htmllib
import json
import re
from datetime import datetime
from urllib.parse import parse_qs, quote, urljoin, urlparse

from bs4 import BeautifulSoup
from dateutil import parser as dparser

from .common import TZ
from .ical import parse_ics

EVENT_LINK = re.compile(
    r"event|calendar|music|live|trivia|happen|what.?s.?on|schedule|special|entertain|shows?\b|"
    r"bingo|karaoke|fish.?fry|lineup|gigs?|raffle|open.?mic|this.?week|upcoming|bands?",
    re.I,
)
SOCIAL = re.compile(r"facebook\.com|instagram\.com|twitter\.com|x\.com|tiktok\.com|yelp\.com|google\.com/maps|untappd", re.I)
ICS_HREF = re.compile(r"\.ics(\?|$)|^webcal:|[?&]ical=1|outlook-ical|format=ical|/ical/", re.I)
GCAL = re.compile(r"calendar\.google\.com/calendar/(?:u/\d+/)?embed\?[^\"'\s<>]+", re.I)


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def same_site(a: str, b: str) -> bool:
    ha, hb = urlparse(a).netloc.lower().removeprefix("www."), urlparse(b).netloc.lower().removeprefix("www.")
    return ha == hb


def candidate_pages(soup: BeautifulSoup, base: str, limit: int = 5) -> list[str]:
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        href = urljoin(base, a["href"]).split("#")[0]
        if not href.startswith("http") or not same_site(href, base) or href.rstrip("/") == base.rstrip("/"):
            continue
        if re.search(r"\.(pdf|jpe?g|png|gif|zip|docx?)$", href, re.I):
            continue
        label = (a.get_text(" ", strip=True) + " " + urlparse(href).path)
        if EVENT_LINK.search(label) and href not in seen:
            seen.add(href)
            out.append(href)
    out.sort(key=lambda u: (0 if re.search(r"event|calendar", u, re.I) else 1, len(u)))
    return out[:limit]


def ics_links(soup: BeautifulSoup, base: str) -> list[str]:
    out = []
    for a in soup.find_all("a", href=True):
        h = a["href"].strip()
        if ICS_HREF.search(h) and not SOCIAL.search(h):
            u = urljoin(base, h.replace("webcal://", "https://", 1))
            if u not in out:
                out.append(u)
    for link in soup.find_all("link", attrs={"type": re.compile("calendar", re.I)}):
        if link.get("href"):
            out.append(urljoin(base, link["href"]))
    return out


def gcal_feeds(html: str) -> list[str]:
    out = []
    for m in GCAL.finditer(htmllib.unescape(html)):
        qs = parse_qs(urlparse("https://" + m.group(0)).query)
        for src in qs.get("src", []):
            u = f"https://calendar.google.com/calendar/ical/{quote(src, safe='')}/public/basic.ics"
            if u not in out:
                out.append(u)
    return out


def looks_tribe(html: str) -> bool:
    return "tribe-events" in html or "/wp-json/tribe/events" in html or "tribe_events" in html


def looks_squarespace(html: str) -> bool:
    return "static1.squarespace.com" in html or "Squarespace" in html[:20000]


def _when(v) -> datetime | None:
    if not v:
        return None
    try:
        d = dparser.isoparse(v) if isinstance(v, str) and re.match(r"\d{4}-\d{2}-\d{2}", v) else dparser.parse(str(v))
    except (ValueError, OverflowError, TypeError):
        return None
    return d.replace(tzinfo=TZ) if d.tzinfo is None else d.astimezone(TZ)


def _price(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).lower()
    if "free" in s or "no cover" in s:
        return 0.0
    m = re.search(r"\$?\s*(\d+(?:\.\d{1,2})?)", s)
    return float(m.group(1)) if m else None


def _walk(node):
    if isinstance(node, list):
        for x in node:
            yield from _walk(x)
    elif isinstance(node, dict):
        yield node
        for k in ("@graph", "subEvent", "event", "events", "itemListElement", "item"):
            if k in node:
                yield from _walk(node[k])


def _image(v) -> str:
    """First usable picture URL from the many shapes feeds use (string, list, {url: ...})."""
    if isinstance(v, list):
        v = v[0] if v else ""
    if isinstance(v, dict):
        v = v.get("url") or v.get("contentUrl") or ""
    v = str(v or "").strip()
    return v if v.startswith(("http://", "https://")) and "isthmus.com" not in v else ""


def page_image(soup) -> str:
    """The picture a page publishes for link previews (og:image / twitter:image)."""
    for attr, val in (("property", "og:image"), ("name", "og:image"), ("name", "twitter:image"), ("property", "twitter:image")):
        m = soup.find("meta", attrs={attr: val})
        if m and m.get("content") and "isthmus.com" not in m["content"]:
            return m["content"].strip()  # may be relative; the caller joins it to the page URL
    return ""


def jsonld_events(html: str, base: str) -> list[dict]:
    soup = soup_of(html)
    out = []
    for tag in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = tag.string or tag.get_text() or ""
        raw = re.sub(r"[\x00-\x1f]", " ", raw)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for node in _walk(data):
            t = node.get("@type", "")
            types = t if isinstance(t, list) else [t]
            if not any(isinstance(x, str) and x.endswith("Event") for x in types):
                continue
            s = _when(node.get("startDate"))
            if not s:
                continue
            offers = node.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            loc = node.get("location") or {}
            if isinstance(loc, list):
                loc = loc[0] if loc else {}
            out.append({
                "title": htmllib.unescape(str(node.get("name", ""))).strip(),
                "start": s, "end": _when(node.get("endDate")),
                "allday": isinstance(node.get("startDate"), str) and len(node["startDate"]) == 10,
                "description": htmllib.unescape(str(node.get("description", "")))[:400],
                "location": loc.get("name", "") if isinstance(loc, dict) else str(loc),
                "url": urljoin(base, node.get("url") or "") if node.get("url") else base,
                "price": _price(offers.get("price") if isinstance(offers, dict) else None),
                "status": str(node.get("eventStatus", "")),
                "image": urljoin(base, _image(node.get("image"))) if _image(node.get("image")) else "",
            })
    return [e for e in out if "Cancelled" not in e.get("status", "")]


def tribe_url(site: str, start: datetime, end: datetime) -> str:
    p = urlparse(site)
    return (f"{p.scheme}://{p.netloc}/wp-json/tribe/events/v1/events?per_page=50"
            f"&start_date={start:%Y-%m-%d}&end_date={end:%Y-%m-%d}")


def tribe_events(payload: dict) -> list[dict]:
    out = []
    for ev in payload.get("events", []):
        s = _when(ev.get("start_date"))
        if not s:
            continue
        venue = ev.get("venue") or {}
        out.append({
            "title": htmllib.unescape(re.sub("<[^>]+>", "", ev.get("title", ""))).strip(),
            "start": s, "end": _when(ev.get("end_date")), "allday": bool(ev.get("all_day")),
            "description": htmllib.unescape(re.sub("<[^>]+>", " ", ev.get("description", "") or ""))[:400].strip(),
            "location": venue.get("venue", "") if isinstance(venue, dict) else "",
            "url": ev.get("url", ""), "price": _price(ev.get("cost")),
            "image": _image(ev.get("image")),
        })
    return out


def squarespace_events(payload: dict, base: str) -> list[dict]:
    items = payload.get("upcoming") or payload.get("items") or []
    out = []
    for it in items:
        sd = it.get("startDate")
        if not isinstance(sd, (int, float)):
            continue
        s = datetime.fromtimestamp(sd / 1000, TZ)
        ed = it.get("endDate")
        out.append({
            "title": htmllib.unescape(it.get("title", "")).strip(),
            "start": s, "end": datetime.fromtimestamp(ed / 1000, TZ) if isinstance(ed, (int, float)) else None,
            "allday": False,
            "description": re.sub("<[^>]+>", " ", it.get("excerpt", "") or "")[:400].strip(),
            "location": (it.get("location") or {}).get("addressTitle", ""),
            "url": urljoin(base, it.get("fullUrl", "")), "price": None,
            "image": _image(it.get("assetUrl")),
        })
    return out


def read_ics(text: str, start: datetime, end: datetime) -> list[dict]:
    if "BEGIN:VCALENDAR" not in text[:2000].upper():
        return []
    return parse_ics(text, start, end)


# ---- weekly specials written as plain text ("Tuesday Trivia 7pm") ----
DAYS = {
    "mon": 0, "monday": 0, "mondays": 0, "tue": 1, "tues": 1, "tuesday": 1, "tuesdays": 1,
    "wed": 2, "weds": 2, "wednesday": 2, "wednesdays": 2, "thu": 3, "thur": 3, "thurs": 3,
    "thursday": 3, "thursdays": 3, "fri": 4, "friday": 4, "fridays": 4, "sat": 5, "saturday": 5,
    "saturdays": 5, "sun": 6, "sunday": 6, "sundays": 6,
}
ACTIVITIES = [
    "trivia", "bingo", "karaoke", "open mic", "open jam", "jam session", "fish fry", "meat raffle",
    "raffle", "euchre", "sheepshead", "cribbage", "darts", "pool league", "pool tournament",
    "live music", "comedy", "dj", "drag", "poetry", "board game", "game night", "happy hour",
    "steak night", "burger night", "taco tuesday", "wing night", "pinball", "bags tournament",
    "meat raffles", "polka", "line dancing", "dance", "music bingo",
]
DAY_RE = re.compile(r"\b(" + "|".join(sorted(DAYS, key=len, reverse=True)) + r")\b\.?", re.I)
TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)|\bnoon\b", re.I)
RANGE_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?\s*(?:-|–|—|to|til|till|until)\s*"
                      r"(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)", re.I)
ACT_RE = re.compile(r"\b(" + "|".join(re.escape(a) for a in sorted(ACTIVITIES, key=len, reverse=True)) + r")\b", re.I)


def weekly_from_text(html: str) -> list[dict]:
    """Lines that name a weekday, an activity and a time. These are suggestions for review."""
    text = soup_of(html).get_text("\n")
    found, seen = [], set()
    for line in (l.strip() for l in text.splitlines()):
        if not 6 < len(line) <= 220:
            continue
        acts, days = ACT_RE.findall(line), DAY_RE.findall(line)
        rng, tm = RANGE_RE.search(line), TIME_RE.search(line)
        if not (acts and days and (rng or tm)):
            continue
        if rng and (not tm or rng.start() <= tm.start()):
            hh, mm, mer = int(rng.group(1)), int(rng.group(2) or 0), (rng.group(3) or rng.group(6))
        elif tm.group(0).lower() == "noon":
            hh, mm, mer = 12, 0, "pm"
        else:
            hh, mm, mer = int(tm.group(1)), int(tm.group(2) or 0), tm.group(3)
        if hh > 12:
            continue
        if mer.lower().startswith("p") and hh != 12:
            hh += 12
        if mer.lower().startswith("a") and hh == 12:
            hh = 0
        dnums = sorted({DAYS[d.lower()] for d in days})
        key = (acts[0].lower(), tuple(dnums), hh, mm)
        if key in seen:
            continue
        seen.add(key)
        found.append({"activity": acts[0].lower(), "days": dnums, "time": f"{hh:02d}:{mm:02d}", "text": line})
    return found
