"""Find coordinates for venues we only know by name (e.g. from a city calendar).

Uses OpenStreetMap's Nominatim search, within its usage policy: an identifying
User-Agent, one request a second, results cached in data/geocode_cache.json, and
at most MAX_NEW new lookups per run.
"""
from __future__ import annotations

import time

import requests

from .common import DATA, UA, load_json, save_json

URL = "https://nominatim.openstreetmap.org/search"
MAX_NEW = 40
VIEWBOX = "-90.40,43.60,-88.60,42.60"  # south-central Wisconsin, preferred but not required


class Geocoder:
    def __init__(self):
        self.cache = load_json(DATA / "geocode_cache.json", {})
        self.new = 0
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA})
        self._last = 0.0

    def find(self, place: str) -> dict | None:
        key = place.strip().lower()
        if not key:
            return None
        if key in self.cache:
            return self.cache[key]
        if self.new >= MAX_NEW:
            return None
        wait = self._last + 1.1 - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.new += 1
        hit = None
        try:
            r = self.s.get(URL, timeout=20, params={"q": place + ", Wisconsin", "format": "jsonv2", "limit": 1,
                                                   "countrycodes": "us", "viewbox": VIEWBOX, "bounded": 0,
                                                   "addressdetails": 1})
            if r.status_code == 200 and r.json():
                j = r.json()[0]
                a = j.get("address", {})
                street = " ".join(x for x in (a.get("house_number"), a.get("road")) if x)
                hit = {"lat": round(float(j["lat"]), 6), "lon": round(float(j["lon"]), 6), "address": street,
                       "city": a.get("city") or a.get("town") or a.get("village") or ""}
        except (requests.RequestException, ValueError, KeyError):
            return None  # not cached: try again next run
        finally:
            self._last = time.monotonic()
        self.cache[key] = hit
        return hit

    def save(self):
        save_json(DATA / "geocode_cache.json", self.cache)
