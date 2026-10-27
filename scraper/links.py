"""Check the links the site sends people to: event pages, menu links and place websites.

Runs after each scrape (the Actions runner can reach the sites; checks are spread out: each link
at most once a week, a few hundred per run, robots.txt respected). A link counts as broken only on
a clear answer (404/410 or a site that no longer exists); sites that refuse cloud servers (401/403/429)
count as "couldn't check", since they usually work for people.

Broken event links fall back to a search on the site, broken menu links to a menu search.
Results: data/link_cache.json (per link) and data/link_report.json (summary).
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import requests

from .common import DATA, Fetcher, load_json, now, save_json

LIMIT, DAYS = 300, 7


def check(f: Fetcher, url: str) -> dict:
    try:
        r = f.get(url)
    except PermissionError:
        return {"ok": None, "why": "robots.txt asks bots not to visit"}
    except requests.exceptions.ConnectionError as e:
        gone = re.search(r"Name or service not known|nodename nor servname|getaddrinfo failed|NameResolution", str(e))
        return {"ok": False if gone else None, "why": "site no longer exists" if gone else "could not connect"}
    except requests.RequestException as e:
        return {"ok": None, "why": type(e).__name__}
    if r is not None:
        return {"ok": True, "why": ""}
    why = f.why.get(url, "")
    if re.search(r"HTTP (404|410)\b", why):
        return {"ok": False, "why": why}
    return {"ok": None, "why": why or "no answer"}


def main():
    events_doc = load_json(DATA / "events.json", {})
    rest_doc = load_json(DATA / "restaurants.json", {})
    acts_doc = load_json(DATA / "activities.json", {})
    events, rests, acts = events_doc.get("events", []), rest_doc.get("restaurants", []), acts_doc.get("activities", [])
    urls = []
    for e in events:
        if e.get("url") and "isthmus.com" not in e["url"]:
            urls.append(e["url"])
    for r in rests:
        urls += [u for u in (r.get("menu"), r.get("website")) if u]
    urls += [a["website"] for a in acts if a.get("website")]
    urls = list(dict.fromkeys(u for u in urls if u.startswith(("http://", "https://"))))

    cache = load_json(DATA / "link_cache.json", {})
    stale = (now() - timedelta(days=DAYS)).isoformat()
    todo = [u for u in urls if cache.get(u, {}).get("checked", "") < stale][:LIMIT]
    f = Fetcher(delay=1.0, timeout=12)
    with ThreadPoolExecutor(max_workers=8) as pool:
        for u, res in zip(todo, pool.map(lambda u: check(f, u), todo)):
            cache[u] = {**res, "checked": now().isoformat()}
    cache = {u: v for u, v in cache.items() if u in set(urls)}  # forget links nobody uses any more
    save_json(DATA / "link_cache.json", cache)

    broken = {u for u, v in cache.items() if v.get("ok") is False}
    for e in events:
        e["link_ok"] = None if e.get("url") not in cache else cache[e["url"]].get("ok")
    for r in rests:
        if r.get("menu") in broken:
            r["menu_broken"] = r.pop("menu")  # the site falls back to a menu search
        r["website_ok"] = cache.get(r.get("website") or "", {}).get("ok")
    save_json(DATA / "events.json", events_doc)
    save_json(DATA / "restaurants.json", rest_doc)

    counts = {"ok": 0, "broken": 0, "couldn't check": 0, "not checked yet": 0}
    for u in urls:
        v = cache.get(u)
        counts["not checked yet" if not v else "ok" if v["ok"] else "broken" if v["ok"] is False else "couldn't check"] += 1
    save_json(DATA / "link_report.json", {"generated_at": now().isoformat(), "links": len(urls), "checked_this_run": len(todo),
                                          **counts, "broken_links": sorted(broken)[:200]})
    print(f"Links: {len(urls)} in use, {len(todo)} checked this run; {counts}")


if __name__ == "__main__":
    main()
