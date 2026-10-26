"""Build data/venues.json from OpenStreetMap plus hand edits in data/venue_overrides.json.

    python -m scraper.venues            # refresh now
    python -m scraper.venues --if-stale 7   # only if the list is older than 7 days
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta

import requests

from .common import DATA, UA, load_json, now, save_json, slug

# Madison plus Middleton, Monona, Fitchburg, Maple Bluff, Shorewood Hills
BBOX = "42.98,-89.57,43.20,-89.20"
MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
LODGE = r"VFW|V\.F\.W|American Legion|Legion Post|AMVETS|Eagles|Moose|Elks|Lions Club|Knights of Columbus|Sons of Norway|Turner|Masonic|Veterans"
QUERY = f"""
[out:json][timeout:120];
(
  nwr["amenity"~"^(bar|pub|biergarten|nightclub|cafe|community_centre|social_club|events_venue|theatre|arts_centre|music_venue|social_centre|library)$"]({BBOX});
  nwr["craft"~"^(brewery|winery|distillery|cider)$"]({BBOX});
  nwr["microbrewery"="yes"]({BBOX});
  nwr["club"~"^(veterans|social|freemasonry)$"]({BBOX});
  nwr["name"~"{LODGE}",i]["amenity"!~"^(parking|grave_yard|bench|school)$"]({BBOX});
  nwr["leisure"~"^(bowling_alley|dance)$"]({BBOX});
);
out center tags;
"""


RESTAURANT_QUERY = f"""
[out:json][timeout:120];
(
  nwr["amenity"~"^(restaurant|fast_food|food_court)$"]["name"]({BBOX});
);
out center tags;
"""
# Rough per-person dinner cost (food plus a soft drink) by cuisine, when OSM has no price.
CHEAP = r"pizza|burger|sandwich|hot_dog|taco|mexican|burrito|kebab|falafel|noodle|ramen|pho|vietnamese|chicken|wings|donut|bagel|deli|bubble_tea|ice_cream|food_cart"
PRICEY = r"steak_house|steak|seafood|french|fine_dining|sushi|tapas|wine|supper_club|oyster"
CUISINE_VIBES = [
    (r"pizza|burger|sandwich|hot_dog|taco|burrito|chicken|wings|deli|diner", ["cheap", "chill"]),
    (r"steak|seafood|french|italian|sushi|tapas|wine|fine_dining|mediterranean|spanish", ["date"]),
    (r"american|regional|supper_club|german|fish|friture|cheese|brewpub|polish", ["classic"]),
    (r"pub|bar|tavern|grill", ["dive"]),
    (r"vegan|vegetarian|coffee|cafe|tea|bakery|brunch|breakfast", ["chill"]),
]


def restaurant_of(el: dict) -> dict | None:
    from .hours import parse as parse_hours
    t = el.get("tags", {})
    name = t.get("name")
    if not name or t.get("brand:wikidata"):  # national and regional chains are left out
        return None
    lat = el.get("lat") or el.get("center", {}).get("lat")
    lon = el.get("lon") or el.get("center", {}).get("lon")
    if lat is None:
        return None
    cuisine = (t.get("cuisine") or "").lower()
    fast = t.get("amenity") == "fast_food"
    price = 12 if fast else 16 if re.search(CHEAP, cuisine) else 40 if re.search(PRICEY, cuisine) else 24
    vibes = []
    for pat, vs in CUISINE_VIBES:
        if re.search(pat, cuisine) or re.search(pat, name.lower()):
            vibes += [v for v in vs if v not in vibes]
    hrs = parse_hours(t.get("opening_hours"))
    return {
        "id": f"osm:{el['type']}/{el['id']}",
        "name": name,
        "cuisine": cuisine.replace("_", " ").replace(";", ", "),
        "fast": fast,
        "price": price,
        "vibes": vibes,
        "address": " ".join(x for x in (t.get("addr:housenumber"), t.get("addr:street")) if x),
        "lat": round(lat, 6), "lon": round(lon, 6),
        "website": clean_url(t.get("website") or t.get("contact:website") or t.get("url")),
        "hours": hrs,
        "bar": t.get("amenity") == "restaurant" and bool(re.search(r"pub|bar|tavern|brew", (name + " " + cuisine).lower())),
    }


def build_restaurants() -> dict:
    out, seen = [], set()
    for el in fetch_osm(RESTAURANT_QUERY):
        r = restaurant_of(el)
        if not r:
            continue
        key = (r["name"].lower(), round(r["lat"], 3), round(r["lon"], 3))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    out.sort(key=lambda r: r["name"].lower())
    return {
        "generated_at": now().isoformat(timespec="seconds"),
        "count": len(out),
        "with_hours": sum(1 for r in out if r["hours"]),
        "with_website": sum(1 for r in out if r["website"]),
        "restaurants": out,
    }


def kind_of(t: dict) -> str:
    name = t.get("name", "")
    a, craft = t.get("amenity", ""), t.get("craft", "")
    if t.get("club") == "veterans" or re.search(r"VFW|V\.F\.W|Legion|AMVETS|Veterans", name, re.I):
        return "veterans"
    if t.get("club") or re.search(LODGE, name, re.I):
        return "lodge"
    if craft in ("brewery", "winery", "distillery", "cider") or t.get("microbrewery") == "yes":
        return "brewery"
    if a in ("bar", "pub", "biergarten", "nightclub"):
        return "bar"
    if a == "cafe":
        return "cafe"
    if a in ("theatre", "arts_centre", "music_venue", "events_venue") or t.get("leisure") in ("bowling_alley", "dance"):
        return "venue"
    if a == "library":
        return "library"
    return "community"


def clean_url(u: str | None) -> str:
    if not u:
        return ""
    u = u.strip().split(";")[0]
    if not re.match(r"https?://", u):
        u = "https://" + u.lstrip("/")
    return u


def fetch_osm(query: str = QUERY) -> list[dict]:
    last = None
    for url in MIRRORS:
        try:
            r = requests.post(url, data={"data": query}, headers={"User-Agent": UA}, timeout=180)
            if r.status_code == 200:
                return r.json().get("elements", [])
            last = f"{url}: HTTP {r.status_code}"
        except (requests.RequestException, ValueError) as e:
            last = f"{url}: {e}"
        print("Overpass mirror failed:", last, file=sys.stderr)
    raise RuntimeError(f"All Overpass mirrors failed ({last})")


def to_venue(el: dict) -> dict | None:
    t = el.get("tags", {})
    name = t.get("name")
    if not name:
        return None
    lat = el.get("lat") or el.get("center", {}).get("lat")
    lon = el.get("lon") or el.get("center", {}).get("lon")
    addr = " ".join(x for x in (t.get("addr:housenumber"), t.get("addr:street")) if x)
    return {
        "id": f"osm:{el['type']}/{el['id']}",
        "name": name,
        "kind": kind_of(t),
        "address": addr,
        "city": t.get("addr:city", ""),
        "lat": lat, "lon": lon,
        "website": clean_url(t.get("website") or t.get("contact:website") or t.get("url")),
        "facebook": clean_url(t.get("contact:facebook") or t.get("facebook")),
        "instagram": clean_url(t.get("contact:instagram") or t.get("instagram")),
        "feeds": [],
    }


def apply_overrides(venues: list[dict], overrides: list[dict]) -> list[dict]:
    by_id = {v["id"]: v for v in venues}
    by_name = {}
    for v in venues:
        by_name.setdefault(v["name"].lower(), v)
    for o in overrides:
        key = o.get("match") or o.get("name", "")
        v = by_id.get(key) or by_name.get(key.lower())
        if o.get("skip"):
            if v:
                v["skip"] = True
            continue
        fields = {k: val for k, val in o.items() if k not in ("match",)}
        if v:
            v.update(fields)
        else:
            nv = {"id": "manual:" + slug(o["name"]), "kind": "bar", "address": "", "city": "", "lat": None,
                  "lon": None, "website": "", "facebook": "", "instagram": "", "feeds": []}
            nv.update(fields)
            venues.append(nv)
            by_id[nv["id"]] = nv
            by_name[nv["name"].lower()] = nv
    for v in venues:
        v["website"] = clean_url(v.get("website"))
    return [v for v in venues if not v.get("skip")]


def build() -> dict:
    seen, venues = set(), []
    for el in fetch_osm():
        v = to_venue(el)
        if not v:
            continue
        key = (v["name"].lower(), round(v["lat"] or 0, 3), round(v["lon"] or 0, 3))
        if key in seen:
            continue
        seen.add(key)
        venues.append(v)
    venues = apply_overrides(venues, load_json(DATA / "venue_overrides.json", []))
    venues.sort(key=lambda v: (v["kind"], v["name"].lower()))
    counts = {}
    for v in venues:
        counts[v["kind"]] = counts.get(v["kind"], 0) + 1
    return {
        "generated_at": now().isoformat(timespec="seconds"),
        "count": len(venues),
        "with_website": sum(1 for v in venues if v["website"]),
        "by_kind": counts,
        "venues": venues,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--if-stale", type=float, metavar="DAYS", help="only refresh when older than DAYS")
    a = ap.parse_args(argv)
    path = DATA / "venues.json"
    rpath = DATA / "restaurants.json"
    if a.if_stale is not None:
        cur = load_json(path, {})
        ts = cur.get("generated_at")
        fresh = ts and now() - datetime.fromisoformat(ts) < timedelta(days=a.if_stale)
        if fresh and rpath.exists():
            print(f"Venue list is fresh ({ts}); skipping.")
            return
    data = build()
    save_json(path, data)
    print(f"Saved {data['count']} venues ({data['with_website']} with websites): {data['by_kind']}")
    rdata = build_restaurants()
    save_json(rpath, rdata)
    print(f"Saved {rdata['count']} restaurants ({rdata['with_hours']} with hours, {rdata['with_website']} with websites)")


if __name__ == "__main__":
    main()
