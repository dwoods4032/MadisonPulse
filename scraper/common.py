"""Shared helpers: time zone, the 14-day window, and a polite HTTP fetcher."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("America/Chicago")  # Madison is on Central time
WINDOW_DAYS = 14
UA = "MadisonPulseBot/0.1 (+https://github.com/dwoods4032/madisonpulse; local events calendar)"
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MAX_BYTES = 3_000_000


def now() -> datetime:
    return datetime.now(TZ)


def window(ref: datetime | None = None) -> tuple[datetime, datetime]:
    """Events from six hours ago (still-running tonight) through 14 days out."""
    ref = ref or now()
    return ref - timedelta(hours=6), ref + timedelta(days=WINDOW_DAYS)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def short_hash(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=False) + "\n")


class Fetcher:
    """requests.Session with robots.txt checks and a per-host delay, safe across threads."""

    def __init__(self, delay: float = 1.5, timeout: float = 15):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"})
        self.delay, self.timeout = delay, timeout
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self._host_locks: dict[str, threading.Lock] = {}

    def _host_lock(self, host: str) -> threading.Lock:
        with self._lock:
            return self._host_locks.setdefault(host, threading.Lock())

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = RobotFileParser()
            try:
                r = self.s.get(base + "/robots.txt", timeout=self.timeout)
                if r.status_code == 200 and "text" in r.headers.get("content-type", "text"):
                    rp.parse(r.text.splitlines())
                else:
                    rp = None  # no robots file: allowed
            except requests.RequestException:
                rp = None
            self._robots[base] = rp
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(UA, url)

    def get(self, url: str, **kw) -> requests.Response | None:
        if not url.startswith(("http://", "https://")):
            return None
        if not self.allowed(url):
            raise PermissionError(f"robots.txt disallows {url}")
        host = urlparse(url).netloc
        with self._host_lock(host):
            wait = self._last.get(host, 0) + self.delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                r = self.s.get(url, timeout=self.timeout, stream=True, **kw)
                body = r.raw.read(MAX_BYTES, decode_content=True)
                r._content = body
                r._content_consumed = True
            finally:
                self._last[host] = time.monotonic()
        if r.status_code >= 400:
            return None
        if not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding or "utf-8"
        return r
