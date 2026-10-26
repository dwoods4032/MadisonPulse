"""Collect the next 14 days of events and write data/events.json.

    python -m scraper.run                  # normal run
    python -m scraper.run --limit 20       # first 20 venues with websites (testing)
    python -m scraper.run --venue "Ideal"  # venues whose name contains this
    python -m scraper.run --rediscover     # re-check every site for event sources
"""
from __future__ import annotations

import argparse
import html
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
    ("trivia", r"trivia|quiz|game night|board game|euchre|sheepshead|cribbage|\bdarts?\b|\bpool\b|\bbags\b|cornhole|pinball|tournament|\bleague"),
    ("music", r"live music|\bbands?\b|concert|\bdj\b|acoustic|jazz|blues|bluegrass|singer|songwriter|\btour\b|\bduo\b|\btrio\b|quartet|polka|orchestra|hip.?hop|\bpunk|\bfolk\b|country|music"),
    ("karaoke", r"karaoke"),
    ("bingo", r"bingo|raffle|pull.?tab"),
    ("comedy", r"comedy|stand.?up|improv|comedian|roast"),
    ("open_mic", r"open mic|open jam|jam session|poetry|slam"),
    ("food", r"fish fry|happy hour|special|steak|burger|taco|wing|brunch|supper|dinner|tasting|pairing|potluck|pancake|breakfast|fry"),
    ("dance", r"dance|drag|line danc|salsa|swing|disco"),
    ("sports", r"packers|badgers|brewers|bucks|watch party|game day|ufc|football|hockey"),
]


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
    """Lowest dollar amount in a description ("$25 adv / $30 door" -> 25), 0 for free, else None."""
    t = text[:600]
    if re.search(r"\bfree (?:entry|admission|show|event)\b|\bno cover\b|\bfree to (?:attend|enter)\b", t, re.I):
        return 0.0
    if re.search(r"\bfree\b(?! parking| refill)", t, re.I) and "$" not in t:
        return 0.0
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


def scrape_venue(f: Fetcher, venue: dict, cache: dict, start, end, rediscover: bool) -> tuple[list[dict], dict]:
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
    status = {"name": venue["name"], "kind": venue["kind"], "website": venue["website"],
              "feeds": [x["type"] for x in feeds], "raw_events": len(raw),
              "error": info.get("error") or ("; ".join(errors) if errors else "")}
    return [normalize(e, venue, "scraped") for e in raw], info, status


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
        "category": categorize(title, e.get("description", "")),
        "price": e.get("price") if e.get("price") is not None else price_from_text(e.get("description") or ""),
        "description": re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", e.get("description") or ""))).strip()[:300],
        "url": e.get("url") or venue.get("website", ""),
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


def dedupe(events: list[dict]) -> list[dict]:
    """Keep one copy per venue, start time and title. Scraped beats weekly."""
    rank = {"scraped": 0, "extra": 1, "weekly": 2}
    best = {}
    for e in sorted(events, key=lambda e: rank.get(e["source"], 3)):
        v = e["venue"].lower()
        k1 = (v, e["start"][:13], norm_title(e["title"])[:40])
        k2 = (v, e["start"][:10], e["category"])
        if k1 in best:
            continue
        if e["source"] == "weekly" and any(
                (x["venue"].lower(), x["start"][:10], x["category"]) == k2 for x in best.values()):
            continue  # the venue posted this night itself
        best[k1] = e
    return list(best.values())


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
    events, report = [], []
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futs = {pool.submit(scrape_venue, f, v, cache, start, end, a.rediscover): v for v in targets}
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
        v = by_name.get(src.get("venue", "").lower()) or {
            "id": "source:" + src["name"], "name": src.get("venue") or src["name"], "kind": src.get("kind", "venue"),
            "address": "", "website": src["url"], "lat": None, "lon": None}
        try:
            events += [normalize(e, v, "extra") for e in read_feed(f, src, start, end)]
        except Exception as e:
            report.append({"name": src["name"], "kind": "source", "website": src["url"], "feeds": [src["type"]],
                           "raw_events": 0, "error": str(e)[:200]})

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
    print(f"{len(events)} events from {sum(1 for r in report if r['raw_events'])} of {len(report)} venues; "
          f"{len(suggestions)} weekly suggestions to review.")


if __name__ == "__main__":
    main()
