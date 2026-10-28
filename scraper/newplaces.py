"""Keep the restaurant list current: add places OpenStreetMap is missing, remove closed ones,
and mark places that opened in the last 6 months as "New".

    python -m scraper.newplaces

Sources (all allowed for automated use):
- Overture Maps places (CDLA-Permissive 2.0, monthly): fills gaps in OpenStreetMap and says
  when a place is permanently closed. Read weekly with DuckDB straight from Overture's public
  S3 bucket, limited to the Madison box.
- City of Madison Alcohol License Review Committee agendas (public meeting records, monthly):
  new alcohol licenses are the dated evidence that a restaurant or bar is new. Read with the
  site's robots.txt respected; the agenda text goes to Claude only to pull out the license list.

A place is "New" only with dated evidence (a new-license approval) within the last 183 days.
Places are never marked new just because we hadn't seen them before.

Files: data/overture_places.json, data/licenses.json (caches), data/closed_places.json (what was
removed and why). restaurants.json / venues.json are updated in place.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from datetime import date, datetime, timedelta

import requests

from .common import DATA, load_json, now, save_json

BBOX = (-89.57, 42.98, -89.20, 43.20)  # west, south, east, north (same area as the OSM lists)
NEW_DAYS = 183
OVERTURE_BUCKET = "https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com"
FOOD = re.compile(r"restaurant|diner|bistro|steakhouse|pizz|burger|taco|sushi|ramen|noodle|bbq|barbecue|"
                  r"gastropub|brewpub|supper_club|food_court|deli|sandwich|wings|seafood|tapas|bakery|"
                  r"ice_cream|dessert|donut|creperie|cafe|coffee", re.I)
BARLIKE = re.compile(r"^(bar|pub|cocktail_bar|wine_bar|sports_bar|lounge|dive_bar|beer_bar|brewery|"
                     r"night_club|beer_garden|whiskey_bar|hookah_bar)$", re.I)


MORE_CHAINS = (r"^(wahlburgers|mrbeast|smokey bones|outback|quiznos|milio'?s|wow bao|krispy krunchy|fox'?s pizza|chuck e|olive garden|texas roadhouse|"
               r"buffalo wild|red lobster|longhorn|cracker barrel|bj'?s rest|noodles|taco john|del taco|jimmy john|"
               r"papa murphy|marco'?s|hungry howie|cici|godfather|sbarro|auntie anne|cinnabon|wetzel|jamba|smoothie king|"
               r"tropical smoothie|potbelly|which wich|firehouse|jersey mike|pita pit|zaxby|culver|cousins|toppers|"
               r"jet'?s|qdoba|moe'?s|chipotle|sweetgreen|cava|panda|pei wei|benihana|hooters|twin peaks|ihop|denny|perkins|"
               r"village inn|bob evans|golden corral|old country|famous dave|dickey'?s|arby|sonic|a&w|dairy queen|"
               r"freddy|steak n shake|white castle|krystal|wingstop|wing ?stop|buffalo wings & rings|charleys|"
               r"great harvest|einstein|bruegger|panera|caribou|starbucks|dunkin|tim horton|biggby|scooter'?s)")
ENTITY = re.compile(r"\b(llc|l\.l\.c|inc|incorporated|corp|corporation|ltd|enterprises?|holdings?|ventures?|franchising|group)\b\.?", re.I)


def public_name(n: str) -> str:
    """'Four Pond LLC dba Mint Mark' -> 'Mint Mark'."""
    m = re.search(r"\b(?:dba|d/b/a|doing business as)\b[:\s]+(.+)$", n or "", re.I)
    return m.group(1).strip() if m else (n or "").strip()


def norm(n: str) -> str:
    n = (n or "").lower().replace("&", " and ")
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    n = re.sub(r"\b(the|and|bar|pub|tavern|restaurant|grill|lounge|cafe|co|company|llc|inc|madison)\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def miles(a, b) -> float:
    r = math.radians
    h = math.sin(r(b[0] - a[0]) / 2) ** 2 + math.cos(r(a[0])) * math.cos(r(b[0])) * math.sin(r(b[1] - a[1]) / 2) ** 2
    return 2 * 3959 * math.asin(math.sqrt(h))


def same_place(a: dict, b: dict) -> bool:
    """Same name (or one contains the other) within about 250 m."""
    if a.get("lat") is None or b.get("lat") is None:
        return False
    if miles((a["lat"], a["lon"]), (b["lat"], b["lon"])) > 0.15:
        return False
    x, y = norm(a.get("name", "")), norm(b.get("name", ""))
    return bool(x and y) and (x == y or (min(len(x), len(y)) >= 5 and (x in y or y in x)))


# ---------------------------------------------------------------- Overture
def latest_release() -> str:
    r = requests.get(f"{OVERTURE_BUCKET}/?list-type=2&prefix=release/&delimiter=/", timeout=30)
    r.raise_for_status()
    rels = sorted(re.findall(r"<Prefix>release/([^/<]+)/</Prefix>", r.text))
    if not rels:
        raise RuntimeError("no Overture releases listed")
    return rels[-1]


def fetch_overture() -> dict:
    import duckdb
    rel = latest_release()
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
    w, s, e, n = BBOX
    q = f"""
      SELECT * EXCLUDE (geometry)
      FROM read_parquet('s3://overturemaps-us-west-2/release/{rel}/theme=places/type=place/*', hive_partitioning=1)
      WHERE bbox.xmin BETWEEN {w} AND {e} AND bbox.ymin BETWEEN {s} AND {n}
    """
    cur = con.execute(q)
    cols = [d[0] for d in cur.description]
    out = []
    for row in cur.fetchall():
        p = dict(zip(cols, row))
        # categories moved to "taxonomy" (primary / hierarchy / alternate) in 2026; older releases used "categories"
        tax = p.get("taxonomy") or p.get("categories") or {}
        tax = tax if isinstance(tax, dict) else {}
        cat = tax.get("primary") or p.get("basic_category") or ""
        alt = " ".join([*(tax.get("alternate") or []), *(tax.get("hierarchy") or []), p.get("basic_category") or ""])
        if not (FOOD.search(cat + " " + alt) or BARLIKE.match(cat)):
            continue
        names = p.get("names") or {}
        addr = (p.get("addresses") or [{}])[0] or {}
        brand = p.get("brand") or {}
        bb = p.get("bbox") or {}
        out.append({
            "id": "ovt:" + str(p.get("id")),
            "name": names.get("primary") if isinstance(names, dict) else "",
            "category": cat, "alt": alt,
            "confidence": round(float(p.get("confidence") or 0), 2),
            "status": p.get("operating_status") or "",
            "website": ((p.get("websites") or [""])[0] or ""),
            "address": addr.get("freeform") or "", "city": addr.get("locality") or "",
            "chain": bool(isinstance(brand, dict) and (brand.get("names") or brand.get("wikidata"))),
            "lat": round(float(bb.get("ymin")), 6), "lon": round(float(bb.get("xmin")), 6),
        })
    return {"release": rel, "fetched": now().isoformat(timespec="seconds"), "count": len(out), "places": out}


# ---------------------------------------------------------------- city alcohol licenses
ALRC_PAGE = "https://www.cityofmadison.com/city-hall/committees/alcohol-license-review-committee"
DATE_RX = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),\s+(20\d\d)")


def agenda_links(html: str) -> list[tuple[str, str]]:
    """(meeting date, agenda url) pairs from the committee page."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        if "View.ashx" not in a["href"] or "M=A" not in a["href"]:
            continue
        ctx, el = "", a
        m = DATE_RX.search(a.get("title", ""))  # "Agenda of the Wednesday, Oct. 21, 2026 5:30pm meeting…"
        if m:
            ctx = datetime.strptime(f"{m.group(1)[:3]} {m.group(2)} {m.group(3)}", "%b %d %Y").date().isoformat()
        for _ in range(0 if ctx else 8):  # else look up a few levels for the meeting's date
            el = el.parent
            if el is None:
                break
            m = DATE_RX.search(el.get_text(" "))
            if m:
                ctx = datetime.strptime(f"{m.group(1)[:3]} {m.group(2)} {m.group(3)}", "%b %d %Y").date().isoformat()
                break
        if ctx:
            out.append((ctx, requests.compat.urljoin(ALRC_PAGE, a["href"])))
    return sorted(set(out))


def read_licenses(cache: dict) -> dict:
    """New alcohol licenses from agendas in the last ~8 months, each agenda read once."""
    from io import BytesIO
    from pypdf import PdfReader
    from .common import Fetcher
    f = Fetcher()
    page = f.get(ALRC_PAGE)
    if page is None:
        cache["error"] = f.why.get(ALRC_PAGE, "committee page unavailable")
        return cache
    key = os.environ.get("ANTHROPIC_API_KEY")
    since = (date.today() - timedelta(days=NEW_DAYS + 60)).isoformat()
    agendas = cache.setdefault("agendas", {})
    links = agenda_links(page.text)
    cache["links_on_page"] = len(links)
    cache["page_debug"] = {"bytes": len(page.text), "view_ashx": page.text.count("View.ashx"), "legistar": page.text.count("legistar"),
                           "final_url": page.url}
    for day, url in links:
        if day < since or url in agendas or day > date.today().isoformat():
            continue
        try:
            r = f.get(url)
        except PermissionError:
            cache["error"] = "agendas blocked by robots.txt"
            break
        if r is None:
            continue
        try:
            text = "\n".join((p.extract_text() or "") for p in PdfReader(BytesIO(r.content)).pages)[:30000]
        except Exception as e:
            agendas[url] = {"date": day, "items": [], "error": f"PDF: {type(e).__name__}"}
            continue
        items = extract_licenses(text, key) if key else []
        agendas[url] = {"date": day, "items": items}
    cache["checked"] = now().isoformat(timespec="seconds")
    return cache


def extract_licenses(text: str, key: str) -> list[dict]:
    prompt = ("Below is a City of Madison Alcohol License Review Committee agenda. List every NEW alcohol "
              "license application (not renewals, not changes of agent or premises, not entity changes). "
              "Reply with JSON only: [{\"business\": legal name, \"trade_name\": the d/b/a name customers see, "
              "\"address\": street address, \"kind\": restaurant/bar/store/other}]. Empty list if none.\n\n" + text)
    try:
        resp = requests.post("https://api.anthropic.com/v1/messages", timeout=90, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": os.environ.get("AI_MODEL", "claude-haiku-5-5"), "max_tokens": 4000,
                  "messages": [{"role": "user", "content": prompt}]})
        ans = "".join(b.get("text", "") for b in resp.json().get("content", []))
        m = re.search(r"\[.*\]", ans, re.S)
        items = json.loads(m.group(0)) if m else []
        return [i for i in items if isinstance(i, dict) and (i.get("trade_name") or i.get("business"))]
    except Exception:
        return []


def street_key(addr: str) -> str:
    """'1301 Regent St.' -> '1301 regent'"""
    m = re.match(r"\s*(\d+)\s+(?:[NSEW]\.?\s+)?([A-Za-z]+)", addr or "")
    return f"{m.group(1)} {m.group(2).lower()}" if m else ""


# ---------------------------------------------------------------- apply
def apply(rest_doc: dict, ven_doc: dict, ovt: dict, lic: dict) -> dict:
    from .venues import CHAINS, cuisine_group
    rests, venues = rest_doc.get("restaurants", []), ven_doc.get("venues", [])
    closed_log = load_json(DATA / "closed_places.json", {})
    stats = {"overture_added": 0, "closed_removed": 0, "new": 0}

    places = [p for p in ovt.get("places", []) if p.get("name") and not p.get("chain")]
    for p in places:
        p["name"] = public_name(p["name"])
    # a name with 4+ locations in the area is a chain
    counts = {}
    for p in places:
        counts[norm(p["name"])] = counts.get(norm(p["name"]), 0) + 1
    # 1. closed: a place Overture says is permanently closed comes off the list
    gone = [p for p in places if p["status"] == "permanently_closed"]
    def is_closed(x):
        for p in gone:
            if same_place(x, p):
                closed_log.setdefault(x["id"], {"name": x["name"], "address": x.get("address", ""),
                                                "why": "Overture: permanently closed", "since": now().date().isoformat()})
                return True
        return False
    keep = [r for r in rests if not is_closed(r)]
    stats["closed_removed"] += len(rests) - len(keep)
    vkeep = [v for v in venues if v.get("kind") not in ("bar", "brewery") or not is_closed(v)]
    stats["closed_removed"] += len(venues) - len(vkeep)

    # 2. additions: open, confident, not a chain, not already on our lists, website alive
    link_cache = load_json(DATA / "link_cache.json", {})
    candidates = []
    for p in places:
        if p["status"] not in ("", "open") or p["confidence"] < 0.7 or re.search(CHAINS, p["name"].lower()) \
                or re.search(MORE_CHAINS, p["name"].lower()) or counts.get(norm(p["name"]), 0) >= 4:
            continue
        if ENTITY.search(p["name"]):
            continue  # a company's registered name ("Pizza Ventures III LLC"), not what's on the sign
        # Overture keeps some long-closed places marked open, so a place it alone knows about is added only
        # when Overture says open, is confident, and the place's website answers (checked by scraper.links)
        if p["status"] != "open" or p["confidence"] < 0.9 or not p["website"]:
            continue
        candidates.append({"name": p["name"], "website": p["website"], "id": p["id"]})
        if (link_cache.get(p["website"]) or {}).get("ok") is not True:
            continue
        if BARLIKE.match(p["category"]) or not re.search(r"restaurant|diner|bistro|steakhouse|pizz|burger|taco|sushi|ramen|"
                                                        r"noodle|bbq|barbecue|gastropub|brewpub|supper_club|seafood|tapas|wings",
                                                        p["category"] + " " + p["alt"], re.I):
            continue
        if any(same_place(p, r) for r in keep) or any(same_place(p, v) for v in vkeep):
            continue
        cuisine = re.sub(r"_?restaurant$", "", p["category"]).replace("_", " ").strip()
        group, dinner = cuisine_group(p["name"], cuisine)
        fast = "fast_food" in p["category"]
        keep.append({"group": group, "dinner": dinner, "alcohol": None, "id": p["id"], "name": p["name"],
                     "cuisine": cuisine, "fast": fast, "price": 12 if fast else 24, "vibes": [],
                     "address": p["address"], "lat": p["lat"], "lon": p["lon"], "website": p["website"],
                     "hours": None, "bar": False, "source": "Overture Maps"})
        stats["overture_added"] += 1

    # 3. new: dated evidence of a new license in the last 6 months
    cutoff = (date.today() - timedelta(days=NEW_DAYS)).isoformat()
    lic_items = [(a["date"], i, url) for url, a in (lic.get("agendas") or {}).items() for i in a.get("items", [])]
    for x in keep + vkeep:
        x.pop("new_since", None); x.pop("new_evidence", None)
        for day, i, url in sorted(lic_items, reverse=True):
            if day < cutoff:
                continue
            names = [norm(i.get("trade_name", "")), norm(i.get("business", ""))]
            nx = norm(x.get("name", ""))
            name_hit = nx and any(n and (n == nx or (min(len(n), len(nx)) >= 5 and (n in nx or nx in n))) for n in names)
            addr_hit = street_key(i.get("address", "")) and street_key(i.get("address", "")) == street_key(x.get("address", ""))
            prefix_hit = nx and any(n and n[:4] == nx[:4] for n in names)
            no_addr = not x.get("address") or not street_key(i.get("address", ""))
            if (name_hit and (addr_hit or no_addr)) or (addr_hit and prefix_hit):
                x["new_since"] = day
                x["new_evidence"] = f"New alcohol license approved at the {day} ALRC meeting"
                stats["new"] += 1
                break

    save_json(DATA / "overture_candidates.json", candidates)  # scraper.links checks these websites
    stats["candidates_waiting"] = sum(1 for c in candidates if (link_cache.get(c["website"]) or {}).get("ok") is not True)
    rest_doc["restaurants"] = sorted(keep, key=lambda r: r["name"].lower())
    rest_doc["count"] = len(rest_doc["restaurants"])
    ven_doc["venues"] = vkeep
    save_json(DATA / "closed_places.json", closed_log)
    return stats


def main():
    rest_doc, ven_doc = load_json(DATA / "restaurants.json", {}), load_json(DATA / "venues.json", {})
    if not rest_doc.get("restaurants"):
        sys.exit("restaurants.json is empty")
    ovt = load_json(DATA / "overture_places.json", {})
    if not ovt or ovt.get("fetched", "") < (now() - timedelta(days=7)).isoformat():
        try:
            ovt = fetch_overture()
            save_json(DATA / "overture_places.json", ovt)
            print(f"Overture {ovt['release']}: {ovt['count']} food and drink places in the Madison area")
        except Exception as e:
            print(f"Overture not refreshed ({type(e).__name__}: {str(e)[:150]}); using the last copy", file=sys.stderr)
    lic = load_json(DATA / "licenses.json", {})
    if lic.get("checked", "") < (now() - timedelta(days=7)).isoformat():
        try:
            lic = read_licenses(lic)
            save_json(DATA / "licenses.json", lic)
        except Exception as e:
            print(f"License agendas not read ({type(e).__name__}: {str(e)[:150]})", file=sys.stderr)
    stats = apply(rest_doc, ven_doc, ovt, lic)
    save_json(DATA / "restaurants.json", rest_doc)
    save_json(DATA / "venues.json", ven_doc)
    rep = {**stats, "overture_release": ovt.get("release"), "agendas_read": len((lic.get("agendas") or {})),
           "licenses_found": sum(len(a.get("items", [])) for a in (lic.get("agendas") or {}).values()),
           "license_error": lic.get("error", ""), "at": now().isoformat(timespec="seconds")}
    save_json(DATA / "newplaces_report.json", rep)
    print("New places:", rep)


if __name__ == "__main__":
    main()
