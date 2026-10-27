"""Collect the next 14 days of events and write data/events.json.

    python -m scraper.run                  # normal run
    python -m scraper.run --limit 20       # first 20 venues with websites (testing)
    python -m scraper.run --venue "Ideal"  # venues whose name contains this
    python -m scraper.run --rediscover     # re-check every site for event sources
"""
from __future__ import annotations

import argparse
import html
import os
import json
import re
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from . import extract as X
from .common import DATA, Fetcher, TZ, load_json, now, save_json, short_hash, window

REDISCOVER_DAYS = 7
CATEGORIES = [
    ("trivia", r"trivia|quiz|game night|board game|dungeons|\bd&d\b|tabletop|euchre|sheepshead|cribbage|\bdarts?\b|\bpool\b|\bbags\b|cornhole|pinball|tournament|\bleague"),
    ("music", r"live music|\bbands?\b|concert|\bdj\b|acoustic|jazz|blues|bluegrass|singer|songwriter|\btour\b|\bduo\b|\btrio\b|quartet|polka|orchestra|hip.?hop|\bpunk|\bfolk\b|country|music|\btrad\b|celtic|fiddle"),
    ("karaoke", r"karaoke"),
    ("bingo", r"bingo|raffle|pull.?tab"),
    ("comedy", r"comedy|stand.?up|improv|comedian|\broast of\b|comedy roast"),
    ("open_mic", r"open mic|open jam|jam session|poetry|slam"),
    ("food", r"fish fry|happy hour|special|steak|burger|taco|wing|brunch|supper|dinner|prime rib|tasting|pairing|potluck|pancake|breakfast|fry"),
    ("dance", r"dance|\bdrag\b|line danc|salsa|swing|disco"),
    ("sports", r"packers|badgers|brewers|bucks|watch party|game day|ufc|football|hockey|basketball|volleyball|soccer|\bvs\.?\b|\bat\b.*\bgame\b"),
    ("film", r"^film:|\bfilm\b|movie|screening|cinema"),
    ("theater", r"theat(?:re|er)|\bplay\b|musical|opera|ballet|symphony|chorale|choir|recital|premiere|matinee|cabaret|burlesque"),
]
# Words that mark a band or artist billing ("X w/ Y", "presents", "album release").
BAND_BILLING = re.compile(r"\bw/|\bwith special guest|\bft\.?\s|\bfeat\.?\s|\bpresents\b|album release|\b(?:EP|LP) release|\btour\b|\b& the\b|\band the\b", re.I)
THEATER_VENUE = re.compile(r"theat(?:re|er)|playhouse|opera|overture|players|stage", re.I)
MUSIC_VENUE = re.compile(r"music hall|saloon|sylvee|majestic|high noon|cafe coda|gamma ray|crystal corner|harmony|north street cabaret|barrymore|bur oak|wisco|rigby|bayou|liquid|the cardinal", re.I)


def categorize_event(title: str, description: str, venue: str, venue_kind: str, hint: str = "") -> str:
    """Category using the title first, then hints from the source and the kind of venue."""
    hint = (hint or "").lower()
    if hint in {"music", "trivia", "karaoke", "bingo", "comedy", "open_mic", "food", "dance", "sports", "film", "theater"}:
        return hint
    c = categorize(title, description)
    if c in ("dance", "other") and THEATER_VENUE.search(venue):
        return "theater"  # a show at a theater (dance performances included) is theater
    if c != "other":
        return c
    if BAND_BILLING.search(title) or (MUSIC_VENUE.search(venue) and not THEATER_VENUE.search(venue)):
        return "music"
    if THEATER_VENUE.search(venue):
        return "theater"
    return c


def categorize(title: str, description: str = "") -> str:
    for name, pat in CATEGORIES:
        if re.search(pat, title.lower()):
            return name
    d = description[:200].lower()
    for name, pat in CATEGORIES:
        if name == "music":
            pat = r"live music|concert|\bdj\b|singer|songwriter"
        if re.search(pat, d):
            return name
    return "other"


# Not a night out: social services, kids' programs, meetings, long exhibits.
SKIP_TITLE = re.compile(
    r"food pantry|\bpantry\b|food distribution|fitness room|open gym|storytime|story time|toddler|\bbaby\b|babies|"
    r"preschool|pre-k|homework|tutor|\besl\b|\bged\b|citizenship|senior meal|community meal|\bmeeting\b|"
    r"office hours|\bclosed\b|\bclinic\b|vaccin|tax prep|job fair|resume|support group|after.?school|"
    r"\bkids?\b|children|\byouth\b|\bteens?\b|tween|\bcamp\b|family storytime|lego|playgroup|"
    r"registration (?:required|open|deadline)|volunteer orientation|blood drive|\bmass\b|worship|bible study",
    re.I)
DAYTIME_KINDS = {"library", "community"}


def keep(e: dict) -> bool:
    if SKIP_TITLE.search(e["title"]):
        return False
    s = datetime.fromisoformat(e["start"])
    if e.get("end"):
        if datetime.fromisoformat(e["end"]) - s > timedelta(hours=36):
            return False  # exhibits and season-long runs
    # libraries and community centers: evening and weekend events only
    if e["venue_kind"] in DAYTIME_KINDS and not e["all_day"] and s.weekday() < 5 and s.hour < 17:
        return False
    return True


def price_from_text(text: str):
    """Ticket price from a description: the door price when listed ("$25 adv / $30 door" -> 30),
    otherwise the lowest amount; 0 for free; None if no price."""
    t = text[:600]
    if re.search(r"\bfree (?:entry|admission|show|event)\b|\bno cover\b|\bfree to (?:attend|enter)\b", t, re.I):
        return 0.0
    if re.search(r"\bfree\b(?! parking| refill)", t, re.I) and "$" not in t:
        return 0.0
    # someone planning the night pays at the door: prefer "day of show" / door prices when listed
    door = [float(v) for v in re.findall(r"\$\s?(\d{1,3}(?:\.\d{2})?)\s*(?:DOS\b|day of(?: the)? show|at the door|door)", t, re.I)]
    door = [v for v in door if 0 < v <= 250]
    if door:
        return min(door)
    vals = [float(v) for v in re.findall(r"\$\s?(\d{1,3}(?:\.\d{2})?)", t)]
    vals = [v for v in vals if 0 < v <= 250]
    return min(vals) if vals else None


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


# ---------------------------------------------------------------- discovery
def discover(f: Fetcher, venue: dict, start, end) -> dict:
    """Look over a venue site and record the event sources it offers."""
    site = venue["website"]
    found = {"checked": now().isoformat(timespec="seconds"), "feeds": [], "pages_checked": [], "weekly": []}
    r = f.get(site)
    if r is None:
        found["error"] = "site unreachable"
        return found
    home = r.url
    pages = [(home, r.text)]
    soup = X.soup_of(r.text)
    for u in X.candidate_pages(soup, home):
        try:
            pr = f.get(u)
        except PermissionError:
            continue
        if pr is not None and "html" in pr.headers.get("content-type", "html"):
            pages.append((pr.url, pr.text))

    feeds = []

    def add(kind, url):
        if not any(x["url"] == url for x in feeds):
            feeds.append({"type": kind, "url": url})

    for url, html in pages:
        found["pages_checked"].append(url)
        s = X.soup_of(html)
        for u in X.ics_links(s, url):
            add("ical", u)
        for u in X.gcal_feeds(html):
            add("ical", u)
        if X.jsonld_events(html, url):
            add("jsonld", url)
        if X.looks_squarespace(html) and re.search(r"event|calendar|show|music", url, re.I):
            add("squarespace", url)
        for w in X.weekly_from_text(html):
            w["source_url"] = url
            found["weekly"].append(w)
    if any(X.looks_tribe(h) for _, h in pages):
        add("tribe", X.tribe_url(home, start, end))
    found["feeds"] = feeds
    return found


# ---------------------------------------------------------------- reading
def read_feed(f: Fetcher, feed: dict, start, end) -> list[dict]:
    kind, url = feed["type"], feed["url"]
    if kind == "tribe":
        url = X.tribe_url(url, start, end)
        out, pages = [], 0
        while url and pages < 4:
            r = f.get(url)
            if r is None:
                break
            try:
                payload = r.json()
            except ValueError:
                break
            out += X.tribe_events(payload)
            url, pages = payload.get("next_rest_url"), pages + 1
        return out
    if kind == "squarespace":
        r = f.get(url.split("?")[0] + "?format=json")
        if r is None:
            return []
        try:
            return X.squarespace_events(r.json(), url)
        except ValueError:
            return []
    r = f.get(url)
    if r is None:
        return []
    if kind == "ical":
        return X.read_ics(r.text, start, end)
    if kind in ("jsonld", "page"):
        return X.jsonld_events(r.text, r.url)
    return []


FEED_RANK = {"tribe": 0, "ical": 1, "squarespace": 1, "jsonld": 2, "page": 2}


def pick_feeds(feeds: list[dict]) -> list[dict]:
    """Drop per-event "add to calendar" links and keep a few real feeds."""
    types = {f["type"] for f in feeds}
    out, icals = [], []
    for f in feeds:
        u = f["url"]
        if f["type"] != "ical":
            if not any(x["type"] == f["type"] and x["url"] == u for x in out):
                out.append(f)
            continue
        if "calendar.google.com" in u:
            icals.append((0, f))
        elif "tribe" in types and "ical=1" in u:
            continue  # the Events Calendar API already covers these
        elif "squarespace" in types and "format=ical" in u:
            continue  # one event each; the Squarespace feed covers them
        elif re.search(r"/events?/[^/?]+/[^?]+|[?&](?:tribe-bar-date|eventDate|occurrence)=", u):
            continue  # a single event's link
        else:
            icals.append((len(u), f))
    icals.sort(key=lambda x: x[0])
    jsonld = [f for f in out if f["type"] == "jsonld"][:4]
    rest = [f for f in out if f["type"] != "jsonld"]
    return rest + [f for _, f in icals[:3]] + jsonld


def scrape_venue(f: Fetcher, venue: dict, cache: dict, start, end, rediscover: bool, reader=None):
    vid = venue["id"]
    info = cache.get(vid)
    stale = (not info or rediscover or info.get("site") != venue["website"]
             or now() - datetime.fromisoformat(info["checked"]) > timedelta(days=REDISCOVER_DAYS))
    if stale:
        info = discover(f, venue, start, end)
        info["site"] = venue["website"]
    feeds = list(venue.get("feeds") or []) + pick_feeds(info.get("feeds", []))
    by_rank, errors = {}, []
    for feed in feeds:
        try:
            got = read_feed(f, feed, start, end)
        except Exception as e:  # one bad feed shouldn't sink the venue
            errors.append(f"{feed['type']}: {type(e).__name__}: {e}"[:200])
            continue
        by_rank.setdefault(FEED_RANK.get(feed["type"], 2), []).extend(got)
    # Use the most reliable kind of source that returned anything. Many WordPress
    # sites publish page data with a wrong time-zone offset, so it is the fallback.
    raw = []
    for r in sorted(by_rank):
        if by_rank[r]:
            raw = by_rank[r]
            break
    source = "scraped"
    # No calendar data: have Claude read the event pages as plain text (when a key is set).
    if not raw and reader is not None and reader.enabled and not info.get("error"):
        pages = info.get("pages_checked") or [venue["website"]]
        eventish = [u for u in pages[1:] if X.EVENT_LINK.search(u)]
        for url in (eventish[:2] or pages[:1]):
            try:
                r = f.get(url)
                if r is not None:
                    raw += reader.read(url, r.text, venue["name"], start, end)
            except Exception as e:
                errors.append(f"ai: {type(e).__name__}: {e}"[:200])
        if raw:
            source = "ai"
            feeds = feeds + [{"type": "ai", "url": ""}]
    status = {"name": venue["name"], "kind": venue["kind"], "website": venue["website"],
              "feeds": [x["type"] for x in feeds], "raw_events": len(raw),
              "error": info.get("error") or ("; ".join(errors) if errors else "")}
    return [normalize(e, venue, source) for e in raw], info, status


def calendar_events(f: Fetcher, src: dict, venues: list[dict], start, end, geo=None) -> tuple[list[dict], dict]:
    """A city-wide iCal feed (e.g. Isthmus). Read at most once a day; keep facts only
    (title, time, venue) and link every listing back to the source."""
    state_path = DATA / "calendar_cache.json"
    cache = load_json(state_path, {})
    name, today = src["name"], now().date().isoformat()
    status = {"name": name, "kind": "source", "website": src["url"], "feeds": ["calendar"], "raw_events": 0, "error": ""}
    hit = cache.get(name)
    if hit and hit.get("on") == today and hit.get("events") and src.get("daily", True):
        raw = [{**e, "start": datetime.fromisoformat(e["start"]), "end": datetime.fromisoformat(e["end"]) if e.get("end") else None}
               for e in hit["events"]]
        status["error"] = "used today's copy (read once a day)"
    else:
        raw, seen = [], set()
        for page in range(1, int(src.get("max_pages", 15)) + 1):
            url = src["url"] if page == 1 else f"{src['url']}{'&' if '?' in src['url'] else '?'}page={page}"
            try:
                r = f.get(url)
            except Exception as e:
                status["error"] = f.why.get(url) or f"{type(e).__name__}: {e}"[:200]
                break
            if r is None:
                status["error"] = f.why.get(url, "no response")
                break
            got = X.read_ics(r.text, start, end)
            if page == 1 and not got:
                ctype = r.headers.get("content-type", "?").split(";")[0]
                title = re.search(r"<title[^>]*>([^<]{0,80})", r.text, re.I)
                cal = "BEGIN:VCALENDAR" in r.text[:2000].upper()
                status["error"] = (f"calendar file had no events in the next 14 days" if cal else
                                   f"got {ctype} instead of a calendar file" + (f' (page title: "{title.group(1).strip()}")' if title else "")
                                   + f", {len(r.text)} bytes")
                break
            fresh = [e for e in got if (e.get("uid"), e["start"].isoformat()) not in seen]
            if not fresh:
                break  # no paging, or past the last page
            for e in fresh:
                seen.add((e.get("uid"), e["start"].isoformat()))
            raw += fresh
            if max(e["start"] for e in got) >= end:
                break  # covered the two weeks
        if raw:  # only a successful read counts as today's read; failures retry next run
            cache[name] = {"on": today, "events": [{"title": e["title"], "start": e["start"].isoformat(),
                           "end": e["end"].isoformat() if e.get("end") else None, "allday": e.get("allday", False),
                           "location": e.get("location", ""), "desc": (e.get("description") or "")[:200]} for e in raw]}
            save_json(state_path, cache)
    by_key = {}
    for v in venues:
        by_key.setdefault(vkey(v["name"]), v)
    out = []
    for e in raw:
        full = (e.get("location") or "").strip()
        loc = full.split(",")[0].strip()
        v = by_key.get(vkey(loc))
        if not v:
            v = {"id": "cal:" + slug_(loc or "unknown"), "name": loc or "Location not listed", "kind": "venue",
                 "address": "", "website": "", "lat": None, "lon": None}
            hit = geo.find(full or loc) if (geo and (full or loc)) else None
            if hit:
                v.update(lat=hit["lat"], lon=hit["lon"], address=hit["address"])
                if hit.get("city") and hit["city"].lower() != "madison":
                    v["city"] = hit["city"]
        if e.get("end") and e["end"] <= e["start"]:
            e = {**e, "end": None}
        # The listing's short note ("Classical. Free/donations.") is used only to label and
        # price the event; it is not shown. Links go to the venue, never back to the calendar.
        desc = e.get("desc") or e.get("description") or ""
        hint = categorize(desc) if desc else ""
        ev = normalize({"title": e["title"], "start": e["start"], "end": e.get("end"), "allday": e.get("allday"),
                        "description": "", "url": v.get("website", ""), "price": price_from_text(desc) if desc else None,
                        "category_hint": "" if hint == "other" else hint}, v, "extra")
        ev["via"] = src.get("attribution", name)
        if v.get("city"):
            ev["city"] = v["city"]
        out.append(ev)
    status["raw_events"] = len(out)
    return out, status


def slug_(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:60]


def vkey(name: str) -> str:
    """Venue name for matching across sources ("The Majestic Theatre" ~ "Majestic")."""
    n = re.sub(r"[^a-z0-9 ]+", " ", name.lower())
    n = re.sub(r"\b(the|theatre|theater|madison|bar|and|saloon|music hall|hall|club|lounge)\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def ticketmaster_events(venues: list[dict], start, end) -> tuple[list[dict], dict]:
    from . import ticketmaster
    if not os.environ.get("TICKETMASTER_KEY"):
        return [], {"name": "Ticketmaster", "kind": "source", "website": "", "feeds": [], "raw_events": 0,
                    "error": "off (no TICKETMASTER_KEY)"}
    by_key = {}
    for v in venues:
        by_key.setdefault(vkey(v["name"]), v)
    out = []
    try:
        raw = ticketmaster.fetch(start, end)
    except Exception as e:
        return [], {"name": "Ticketmaster", "kind": "source", "website": "", "feeds": ["ticketmaster"],
                    "raw_events": 0, "error": f"{type(e).__name__}: {e}"[:200]}
    for e in raw:
        v = by_key.get(vkey(e["venue_name"])) or {
            "id": "tm:" + (e["venue_tm_id"] or e["venue_name"]), "name": e["venue_name"] or "Ticketmaster venue",
            "kind": "venue", "address": e["venue_address"], "website": "", "lat": e["venue_lat"], "lon": e["venue_lon"]}
        out.append(normalize(e, v, "ticketmaster"))
    return out, {"name": "Ticketmaster", "kind": "source", "website": "", "feeds": ["ticketmaster"],
                 "raw_events": len(out), "error": ""}


# ---------------------------------------------------------------- shaping
def normalize(e: dict, venue: dict, source: str) -> dict:
    s: datetime = e["start"]
    title = re.sub(r"\s+", " ", html.unescape(html.unescape(e.get("title") or ""))).strip() or "Event"
    return {
        "id": short_hash(venue["id"], s.isoformat(), norm_title(title)),
        "title": title[:140],
        "start": s.isoformat(timespec="minutes"),
        "end": e["end"].isoformat(timespec="minutes") if e.get("end") else None,
        "all_day": bool(e.get("allday")),
        "category": categorize_event(title, e.get("description", ""), venue["name"], venue.get("kind", ""), e.get("category_hint", "")),
        "price": e.get("price") if e.get("price") is not None else price_from_text(e.get("description") or ""),
        "description": re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", e.get("description") or ""))).strip()[:300],
        "url": e.get("url") or venue.get("website", ""),
        "image": e.get("image") if str(e.get("image") or "").startswith("http") and "isthmus.com" not in str(e.get("image")) else "",
        "venue": venue["name"], "venue_id": venue["id"], "venue_kind": venue["kind"],
        "address": venue.get("address", ""),
        "lat": venue.get("lat"), "lon": venue.get("lon"),
        "source": source,
    }


def expand_recurring(items: list[dict], venues_by: dict, start: datetime, end: datetime) -> list[dict]:
    """Turn weekly entries in data/recurring.json into dated events."""
    out = []
    for r in items:
        v = venues_by.get(r.get("venue", "").lower()) or {
            "id": "manual:" + r.get("venue", "?"), "name": r.get("venue", "?"), "kind": r.get("kind", "bar"),
            "address": r.get("address", ""), "website": r.get("url", ""), "lat": None, "lon": None}
        hh, mm = (int(x) for x in r.get("time", "19:00").split(":"))
        dur = timedelta(minutes=int(r.get("minutes", 180)))
        days = r.get("days", [])
        nth = r.get("weeks")  # optional: [1,3] for first and third week of the month
        d = start.date()
        while d <= end.date():
            if d.weekday() in days and (not nth or ((d.day - 1) // 7 + 1) in nth):
                s = datetime(d.year, d.month, d.day, hh, mm, tzinfo=TZ)
                if start <= s + dur and s < end and d.isoformat() not in r.get("skip_dates", []):
                    ev = normalize({"title": r["title"], "start": s, "end": s + dur, "price": r.get("price"),
                                    "description": r.get("note", ""), "url": r.get("url", "")}, v, "weekly")
                    if r.get("category"):
                        ev["category"] = r["category"]
                    ev["confirm"] = r.get("confirm_url") or v.get("facebook") or ""
                    out.append(ev)
            d += timedelta(days=1)
    return out


SOURCE_LABEL = {"scraped": "Venue websites", "ticketmaster": "Ticketmaster", "ai": "AI page reading",
                "weekly": "Weekly routines"}


def source_label(e: dict) -> str:
    if e["source"] == "extra":
        return e.get("via") or "Other calendars"
    return SOURCE_LABEL.get(e["source"], e["source"])


def dedupe(events: list[dict]) -> list[dict]:
    """Keep one copy per venue, start time and title (scraped beats weekly), and record
    every source that had the event in e["sources"]."""
    rank = {"scraped": 0, "ticketmaster": 1, "extra": 2, "ai": 3, "weekly": 4}
    best = {}
    for e in sorted(events, key=lambda e: rank.get(e["source"], 5)):
        v = vkey(e["venue"])
        k1 = (v, e["start"][:13], norm_title(e["title"])[:12])
        k2 = (v, e["start"][:10], e["category"])
        lab = source_label(e)
        if k1 not in best:
            nt = norm_title(e["title"])
            for k, x in best.items():
                if k[0] == v and k[1] == k1[1]:
                    xt = norm_title(x["title"])
                    m = min(len(nt), len(xt), 10)
                    if m >= 5 and nt[:m] == xt[:m]:
                        k1 = k  # same show under a longer or shorter name
                        break
        if k1 in best:
            if lab not in best[k1]["sources"]:
                best[k1]["sources"].append(lab)
            if not best[k1].get("image") and e.get("image"):
                best[k1]["image"] = e["image"]  # another source had a picture
            continue
        if e["source"] == "weekly":
            same = next((x for x in best.values() if (vkey(x["venue"]), x["start"][:10], x["category"]) == k2), None)
            if same:  # the venue posted this night itself
                if lab not in same["sources"]:
                    same["sources"].append(lab)
                continue
        e["sources"] = [lab]
        best[k1] = e
    return list(best.values())


def source_report(events: list[dict]) -> dict:
    """What each source adds: total, unique (no other source had it), overlap, venues only it covers."""
    labels = sorted({l for e in events for l in e.get("sources", [])})
    out = {}
    for lab in labels:
        mine = [e for e in events if lab in e["sources"]]
        venues = {e["venue"] for e in mine}
        others = {e["venue"] for e in events if any(l != lab for l in e["sources"])}
        out[lab] = {
            "events": len(mine),
            "unique_events": sum(1 for e in mine if e["sources"] == [lab]),
            "overlap": {o: sum(1 for e in mine if o in e["sources"]) for o in labels if o != lab},
            "venues": len(venues),
            "unique_venues": sorted(venues - others),
        }
    return {"generated_at": now().isoformat(timespec="seconds"), "total_events": len(events),
            "in_more_than_one_source": sum(1 for e in events if len(e.get("sources", [])) > 1), "sources": out}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--venue")
    ap.add_argument("--rediscover", action="store_true")
    ap.add_argument("--workers", type=int, default=10)
    a = ap.parse_args(argv)

    vdata = load_json(DATA / "venues.json", {})
    venues = vdata.get("venues", [])
    if not venues:
        sys.exit("data/venues.json is empty. Run: python -m scraper.venues")
    start, end = window()
    cache = load_json(DATA / "venue_sources.json", {})
    targets = [v for v in venues if v.get("website") or v.get("feeds")]
    if a.venue:
        targets = [v for v in targets if a.venue.lower() in v["name"].lower()]
    if a.limit:
        targets = targets[: a.limit]

    f = Fetcher()
    from .geocode import Geocoder
    geo = Geocoder()
    from .ai_read import Reader
    reader = Reader()
    events, report = [], []
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(scrape_venue, f, v, cache, start, end, a.rediscover, reader): v for v in targets}
        for fut in as_completed(futs):
            v = futs[fut]
            try:
                evs, info, status = fut.result()
                cache[v["id"]] = info
                events += evs
                report.append(status)
            except Exception as e:
                report.append({"name": v["name"], "kind": v["kind"], "website": v.get("website"),
                               "feeds": [], "raw_events": 0, "error": f"{type(e).__name__}: {e}"[:200]})
                traceback.print_exc(file=sys.stderr)

    # extra calendars that aren't one venue's website (a library system, a neighborhood group)
    by_name = {v["name"].lower(): v for v in venues}
    for src in load_json(DATA / "sources.json", []):
        if src.get("type") == "calendar":  # a city-wide calendar: many venues, facts only
            evs, st = calendar_events(f, src, venues, start, end, geo)
            events += evs
            report.append(st)
            continue
        v = by_name.get(src.get("venue", "").lower()) or {
            "id": "source:" + src["name"], "name": src.get("venue") or src["name"], "kind": src.get("kind", "venue"),
            "address": "", "website": src["url"], "lat": None, "lon": None}
        try:
            events += [normalize(e, v, "extra") for e in read_feed(f, src, start, end)]
        except Exception as e:
            report.append({"name": src["name"], "kind": "source", "website": src["url"], "feeds": [src["type"]],
                           "raw_events": 0, "error": str(e)[:200]})

    tm, tm_status = ticketmaster_events(venues, start, end)
    events += tm
    report.append(tm_status)
    report.append({"name": "AI page reading", "kind": "source", "website": "", "feeds": ["ai"] if reader.enabled else [],
                   "raw_events": sum(1 for e in events if e["source"] == "ai"),
                   "error": "" if reader.enabled else "off (no ANTHROPIC_API_KEY)", "calls": reader.calls,
                   "tokens_in": reader.tokens_in, "tokens_out": reader.tokens_out,
                   "est_cost_usd": round(reader.tokens_in / 1e6 * 0.10 + reader.tokens_out / 1e6 * 0.50, 4)})
    if reader.enabled:
        reader.save()
    events += expand_recurring(load_json(DATA / "recurring.json", []), by_name, start, end)
    events = [e for e in events if start <= datetime.fromisoformat(e["end"] or e["start"]) and
              datetime.fromisoformat(e["start"]) < end]
    dropped = sum(1 for e in events if not keep(e))
    events = sorted(dedupe([e for e in events if keep(e)]), key=lambda e: (e["start"], e["venue"]))

    suggestions = []
    for vid, info in cache.items():
        for w in info.get("weekly", []):
            name = next((v["name"] for v in venues if v["id"] == vid), vid)
            suggestions.append({"venue": name, **w})

    save_json(DATA / "venue_sources.json", cache)
    save_json(DATA / "events.json", {
        "generated_at": now().isoformat(timespec="seconds"),
        "window": {"from": start.isoformat(timespec="minutes"), "to": end.isoformat(timespec="minutes")},
        "count": len(events), "events": events})
    report.sort(key=lambda r: (-r["raw_events"], r["name"]))
    save_json(DATA / "report.json", {
        "generated_at": now().isoformat(timespec="seconds"),
        "venues_checked": len(report),
        "venues_with_events": sum(1 for r in report if r["raw_events"]),
        "venues_with_feeds": sum(1 for r in report if r["feeds"]),
        "events": len(events), "filtered_out": dropped, "venues": report})
    save_json(DATA / "weekly_suggestions.json", suggestions)
    save_json(DATA / "sources_report.json", source_report(events))
    geo.save()
    print(f"{len(events)} events from {sum(1 for r in report if r['raw_events'])} of {len(report)} venues; "
          f"{len(suggestions)} weekly suggestions to review.")


if __name__ == "__main__":
    main()
