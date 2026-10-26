"""Ticketmaster Discovery API: ticketed shows in the Madison area.

Free key from developer.ticketmaster.com, stored as the GitHub secret TICKETMASTER_KEY.
Without a key this returns nothing.
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from .common import TZ, UA

URL = "https://app.ticketmaster.com/discovery/v2/events.json"
CENTER = "43.0731,-89.4012"  # Capitol Square


def fetch(start: datetime, end: datetime, key: str | None = None, session=None) -> list[dict]:
    key = key or os.environ.get("TICKETMASTER_KEY")
    if not key:
        return []
    s = session or requests.Session()
    utc = ZoneInfo("UTC")
    params = {"apikey": key, "latlong": CENTER, "radius": 20, "unit": "miles", "size": 199,
              "sort": "date,asc", "locale": "*",
              "startDateTime": start.astimezone(utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "endDateTime": end.astimezone(utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    out, page = [], 0
    while page < 5:
        params["page"] = page
        r = s.get(URL, params=params, headers={"User-Agent": UA}, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"Ticketmaster HTTP {r.status_code}: {r.text[:120]}")
        data = r.json()
        out += parse(data)
        pages = data.get("page", {}).get("totalPages", 1)
        page += 1
        if page >= pages:
            break
        time.sleep(0.3)
    return out


def tm_category(cls: dict) -> str:
    seg = (cls.get("segment") or {}).get("name", "")
    genre = (cls.get("genre") or {}).get("name", "")
    if genre == "Comedy":
        return "comedy"
    if seg == "Music":
        return "music"
    if seg == "Sports":
        return "sports"
    if seg == "Film":
        return "film"
    if seg == "Arts & Theatre":
        return "theater"
    return ""


def parse(data: dict) -> list[dict]:
    out = []
    for ev in data.get("_embedded", {}).get("events", []):
        st = ev.get("dates", {}).get("start", {})
        if ev.get("dates", {}).get("status", {}).get("code") in ("cancelled", "postponed"):
            continue
        d, t = st.get("localDate"), st.get("localTime")
        if not d:
            continue
        start = datetime.fromisoformat(f"{d}T{(t or '00:00:00')[:8]}").replace(tzinfo=TZ)
        venues = ev.get("_embedded", {}).get("venues", [{}])
        v = venues[0] if venues else {}
        loc = v.get("location") or {}
        prices = ev.get("priceRanges") or []
        cls = (ev.get("classifications") or [{}])[0]
        out.append({
            "title": ev.get("name", "").strip(),
            "start": start, "end": None, "allday": not t,
            "url": ev.get("url", ""),
            "price": prices[0].get("min") if prices else None,
            "description": " / ".join(x for x in (cls.get("genre", {}).get("name"), cls.get("subGenre", {}).get("name")) if x and x != "Undefined"),
            "venue_name": v.get("name", ""),
            "venue_address": (v.get("address") or {}).get("line1", ""),
            "venue_lat": float(loc["latitude"]) if loc.get("latitude") else None,
            "venue_lon": float(loc["longitude"]) if loc.get("longitude") else None,
            "venue_tm_id": v.get("id", ""),
            "segment": cls.get("segment", {}).get("name", ""),
            "category_hint": tm_category(cls),
        })
    return out
