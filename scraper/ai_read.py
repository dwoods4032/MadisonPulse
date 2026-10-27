"""Read events written as plain text on a venue's page, using Claude.

Used only for venue pages where no calendar data was found. Needs the GitHub secret
ANTHROPIC_API_KEY; without it this does nothing. Results are cached by page content
so an unchanged page is not sent again, and each run is capped at AI_MAX_CALLS pages.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime, timedelta

import requests

from .common import DATA, TZ, load_json, now, save_json

API = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("AI_MODEL", "claude-haiku-5-5")
MAX_CALLS = int(os.environ.get("AI_MAX_CALLS", "300"))
MAX_CHARS = 9000
# Sites that have opted out of AI tools (robots.txt blocks AI crawlers): never sent to Claude.
NO_AI = re.compile(r"https?://(?:[^/]*\.)?(?:isthmus\.com)(?:/|$)", re.I)
DATEISH = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b|\b\d{1,2}/\d{1,2}\b|"
                     r"\b(mon|tues?|wed(nes)?|thu(rs)?|fri|sat(ur)?|sun)(day)?s?\b", re.I)
SYSTEM = (
    "You extract events from the text of a bar, venue or community website in Madison, Wisconsin. "
    "Return only JSON. List each event the page states, with its date. If the page gives a weekly "
    "routine (for example 'Every Tuesday: trivia 7pm'), list it once per matching date in the window. "
    "Use only facts on the page: do not guess times, prices or dates. Skip anything without a date or "
    "weekday, anything outside the window, and menus, hours, or private-event offers."
)


class Reader:
    def __init__(self, key: str | None = None):
        self.key = key or os.environ.get("ANTHROPIC_API_KEY")
        self.cache = load_json(DATA / "ai_cache.json", {})
        self.calls = 0
        self.tokens_in = self.tokens_out = 0
        self.lock = threading.Lock()
        self.s = requests.Session()

    @property
    def enabled(self) -> bool:
        return bool(self.key)

    def page_text(self, html: str) -> str:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for t in soup(["script", "style", "noscript", "svg", "nav", "footer", "form"]):
            t.decompose()
        text = re.sub(r"\n\s*\n+", "\n", soup.get_text("\n"))
        return re.sub(r"[ \t]+", " ", text).strip()[:MAX_CHARS]

    def read(self, url: str, html: str, venue: str, start: datetime, end: datetime) -> list[dict]:
        if not self.enabled or NO_AI.search(url):
            return []
        text = self.page_text(html)
        if len(text) < 80 or len(DATEISH.findall(text)) < 2:
            return []
        h = hashlib.sha1(text.encode()).hexdigest()
        today = now().date().isoformat()
        hit = self.cache.get(url)
        # unchanged page: reuse for 3 days (re-ask sooner only if the text changed)
        if hit and hit.get("hash") == h and (now() - datetime.fromisoformat(hit["asked"])) < timedelta(days=3):
            return self._events(hit["events"], start, end)
        with self.lock:
            if self.calls >= MAX_CALLS:
                return self._events(hit["events"], start, end) if hit else []
            self.calls += 1
        prompt = (f"Venue: {venue}\nPage: {url}\nToday is {now():%A, %B %d, %Y} (Central time). "
                  f"Window: {start.date()} to {end.date()}.\n\n"
                  'Reply with {"events": [{"title": str, "date": "YYYY-MM-DD", "start": "HH:MM" or null, '
                  '"end": "HH:MM" or null, "price": number or null, "description": short str, '
                  '"category": one of music, comedy, theater, film, trivia, karaoke, bingo, open_mic, dance, sports, food, other}]}. '
                  'Use "music" for any band, DJ or performer billing. '
                  'Use 24-hour times. Return {"events": []} if there are none.\n\nPAGE TEXT:\n' + text)
        r = self.s.post(API, timeout=60, headers={
            "x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": MODEL, "max_tokens": 2500, "system": SYSTEM,
                  "messages": [{"role": "user", "content": prompt}]})
        if r.status_code != 200:
            raise RuntimeError(f"AI read HTTP {r.status_code}: {r.text[:150]}")
        body = r.json()
        usage = body.get("usage") or {}
        with self.lock:
            self.tokens_in += int(usage.get("input_tokens") or 0)
            self.tokens_out += int(usage.get("output_tokens") or 0)
        raw = "".join(b.get("text", "") for b in body.get("content", []))
        items = parse_reply(raw)
        with self.lock:
            self.cache[url] = {"hash": h, "asked": now().isoformat(timespec="seconds"), "on": today, "events": items}
        return self._events(items, start, end)

    def _events(self, items: list[dict], start: datetime, end: datetime) -> list[dict]:
        out = []
        for it in items:
            try:
                d = datetime.fromisoformat(it["date"])
            except (KeyError, TypeError, ValueError):
                continue
            st = it.get("start")
            allday = not (isinstance(st, str) and re.fullmatch(r"\d{1,2}:\d{2}", st))
            hh, mm = (0, 0) if allday else (int(x) for x in st.split(":"))
            if not allday and hh > 23:
                continue
            s = datetime(d.year, d.month, d.day, hh, mm, tzinfo=TZ)
            e = None
            en = it.get("end")
            if not allday and isinstance(en, str) and re.fullmatch(r"\d{1,2}:\d{2}", en):
                eh, em = (int(x) for x in en.split(":"))
                e = s.replace(hour=eh % 24, minute=em) + (timedelta(days=1) if eh * 60 + em <= hh * 60 + mm else timedelta(0))
            if not (start - timedelta(hours=6) <= s < end):
                continue
            price = it.get("price")
            out.append({"title": str(it.get("title", "")).strip()[:140], "start": s, "end": e, "allday": allday,
                        "category_hint": str(it.get("category") or ""),
                        "description": str(it.get("description") or "")[:300],
                        "price": float(price) if isinstance(price, (int, float)) else None})
        return [x for x in out if x["title"]]

    def save(self):
        # keep the cache small: drop entries not asked in 30 days
        cutoff = now() - timedelta(days=30)
        self.cache = {u: v for u, v in self.cache.items() if datetime.fromisoformat(v["asked"]) > cutoff}
        save_json(DATA / "ai_cache.json", self.cache)


def parse_reply(raw: str) -> list[dict]:
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    evs = data.get("events", []) if isinstance(data, dict) else []
    return [e for e in evs if isinstance(e, dict)]
