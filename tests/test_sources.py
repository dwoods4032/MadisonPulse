"""Ticketmaster, AI page reading, opening hours and restaurants."""
import json
import unittest
from datetime import datetime, timedelta
from unittest import mock

from scraper import ai_read, ticketmaster
from scraper.common import TZ
from scraper.hours import parse as hours
from scraper.run import dedupe, normalize, vkey
from scraper.venues import restaurant_of

START = datetime(2026, 10, 26, 12, 0, tzinfo=TZ)
END = START + timedelta(days=14)
TM = {"_embedded": {"events": [
    {"name": "Low Cut Connie", "url": "https://tm/e/1", "dates": {"start": {"localDate": "2026-11-11", "localTime": "20:00:00"},
     "status": {"code": "onsale"}}, "priceRanges": [{"min": 22.5}],
     "classifications": [{"segment": {"name": "Music"}, "genre": {"name": "Rock"}, "subGenre": {"name": "Undefined"}}],
     "_embedded": {"venues": [{"id": "KovZ1", "name": "High Noon Saloon", "address": {"line1": "701 E Washington Ave"},
                               "location": {"latitude": "43.0802", "longitude": "-89.3741"}}]}},
    {"name": "Called off", "dates": {"start": {"localDate": "2026-11-12", "localTime": "20:00:00"}, "status": {"code": "cancelled"}}}]}}


class SourceTests(unittest.TestCase):
    def test_ticketmaster_parse(self):
        evs = ticketmaster.parse(TM)
        self.assertEqual(len(evs), 1)
        e = evs[0]
        self.assertEqual((e["title"], e["price"], e["start"].hour, e["venue_name"], e["description"]),
                         ("Low Cut Connie", 22.5, 20, "High Noon Saloon", "Rock"))

    def test_ticketmaster_off_without_key(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(ticketmaster.fetch(START, END), [])

    def test_vkey_matches_across_sources(self):
        self.assertEqual(vkey("The Majestic Theatre"), vkey("Majestic"))
        self.assertEqual(vkey("High Noon Saloon"), vkey("High Noon"))
        self.assertNotEqual(vkey("Crystal Corner Bar"), vkey("Corner Bar"))

    def test_dedupe_across_sources(self):
        v1 = {"id": "osm:1", "name": "High Noon Saloon", "kind": "bar", "website": "https://high-noon.com"}
        v2 = {"id": "tm:K", "name": "High Noon", "kind": "venue", "website": ""}
        s = datetime(2026, 11, 11, 20, 0, tzinfo=TZ)
        a = normalize({"title": "Low Cut Connie with Free Dirt", "start": s}, v1, "ai")
        b = normalize({"title": "LOW CUT CONNIE", "start": s, "price": 22.5}, v2, "ticketmaster")
        out = dedupe([a, b])
        self.assertEqual([x["source"] for x in out], ["ticketmaster"])

    def test_ai_reply_to_events(self):
        reply = 'Here you go:\n```json\n' + json.dumps({"events": [
            {"title": "Trivia", "date": "2026-10-27", "start": "19:00", "end": "21:00", "price": None, "description": "Weekly"},
            {"title": "Late band", "date": "2026-10-30", "start": "22:30", "end": "01:00", "price": 5},
            {"title": "No time", "date": "2026-10-31", "start": None},
            {"title": "Way later", "date": "2027-01-05", "start": "19:00"},
            {"title": "Bad date", "date": "Friday", "start": "19:00"}]}) + "\n```"
        items = ai_read.parse_reply(reply)
        r = ai_read.Reader(key="x")
        evs = r._events(items, START, END)
        got = [(e["title"], e["start"].strftime("%m-%d %H:%M"), e["allday"], e["end"].strftime("%m-%d %H:%M") if e["end"] else None)
               for e in evs]
        self.assertEqual(got, [("Trivia", "10-27 19:00", False, "10-27 21:00"),
                               ("Late band", "10-30 22:30", False, "10-31 01:00"),
                               ("No time", "10-31 00:00", True, None)])

    def test_ai_cache_and_cap(self):
        r = ai_read.Reader(key="x")
        r.cache = {}
        html = "<p>Tuesday Oct 27: Trivia 7pm</p><p>Friday Oct 30: Band 9pm</p>" + "<p>filler</p>" * 20
        reply = {"content": [{"type": "text", "text": json.dumps({"events": [{"title": "Trivia", "date": "2026-10-27", "start": "19:00"}]})}]}
        fake = mock.Mock(status_code=200, json=lambda: reply)
        with mock.patch.object(r.s, "post", return_value=fake) as post, mock.patch("scraper.ai_read.now", return_value=START):
            self.assertEqual(len(r.read("https://x/events", html, "X", START, END)), 1)
            self.assertEqual(len(r.read("https://x/events", html, "X", START, END)), 1)  # cached
            self.assertEqual(post.call_count, 1)
        r2 = ai_read.Reader(key=None)
        self.assertEqual(r2.read("https://x", html, "X", START, END), [])  # off without a key


class PlaceTests(unittest.TestCase):
    def test_hours(self):
        self.assertEqual(hours("Mo-Th 11:00-22:00; Fr,Sa 11:00-02:00; Su off"),
                         [[[0, 1, 2, 3], "11:00", "22:00"], [[4, 5], "11:00", "26:00"]])
        self.assertEqual(hours("24/7"), [[list(range(7)), "00:00", "24:00"]])
        self.assertIsNone(hours("sunrise-sunset"))
        self.assertIsNone(hours(None))

    def test_restaurant(self):
        r = restaurant_of({"type": "node", "id": 9, "lat": 43.07, "lon": -89.38, "tags": {
            "name": "Taqueria Uno", "amenity": "restaurant", "cuisine": "mexican", "website": "tu.example",
            "opening_hours": "Mo-Su 11:00-22:00"}})
        self.assertEqual((r["price"], r["website"], r["bar"]), (16, "https://tu.example", False))
        self.assertIsNone(restaurant_of({"type": "node", "id": 1, "lat": 43, "lon": -89,
                                         "tags": {"name": "Chain", "amenity": "fast_food", "brand:wikidata": "Q1"}}))


if __name__ == "__main__":
    unittest.main()


class CalendarFeedTests(unittest.TestCase):
    def test_city_calendar_facts_only_and_daily(self):
        import tempfile, pathlib
        from scraper import run
        ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:Trio 5\r\nDTSTART:20261027T010000Z\r\nDTEND:20261027T010000Z\r\n"
               "UID:a1\r\nDESCRIPTION:Free. Long house-written blurb.\r\nLOCATION:High Noon Saloon\r\nEND:VEVENT\r\n"
               "BEGIN:VEVENT\r\nSUMMARY:Poetry night\r\nDTSTART:20261028T000000Z\r\nUID:a2\r\nLOCATION:Somewhere New, 1 Main St\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
        calls = []
        class F:
            def get(self, url):
                calls.append(url)
                return mock.Mock(text=ics, url=url)  # same page every time: feed ignores paging
        venues = [{"id": "osm:1", "name": "High Noon Saloon", "kind": "bar", "address": "701 E Washington",
                   "website": "https://high-noon.com", "lat": 43.08, "lon": -89.37}]
        src = {"name": "Isthmus calendar", "type": "calendar", "attribution": "Isthmus", "url": "https://x/calendar.ics",
               "link": "https://x/calendar/", "daily": True}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(run, "DATA", pathlib.Path(d)), \
                mock.patch("scraper.run.now", return_value=START):
            evs, st = run.calendar_events(F(), src, venues, START, END)
            self.assertEqual(len(calls), 2)                      # page 2 repeated page 1, so it stopped
            self.assertEqual(sorted(e["title"] for e in evs), ["Poetry night", "Trio 5"])
            trio = next(e for e in evs if e["title"] == "Trio 5")
            self.assertEqual((trio["venue"], trio["lat"], trio["description"], trio["via"], trio["url"]),
                             ("High Noon Saloon", 43.08, "", "Isthmus", "https://high-noon.com"))
            self.assertEqual(trio["price"], 0.0)                 # "Free." used internally, not shown
            self.assertNotIn("isthmus", (trio["url"] + str(trio)).lower().replace("'via': 'isthmus'", ""))
            self.assertEqual(trio["start"][11:16], "20:00")      # 01:00 UTC = 8 pm Central
            evs2, st2 = run.calendar_events(F(), src, venues, START, END)
            self.assertEqual(len(calls), 2)                      # second run the same day: no new requests
            self.assertEqual(len(evs2), 2)

    def test_ai_reader_skips_opted_out_sites(self):
        r = ai_read.Reader(key="x")
        with mock.patch.object(r.s, "post") as post:
            self.assertEqual(r.read("https://isthmus.com/events/x/", "<p>Tue Oct 27 trivia 7pm Fri Oct 30</p>" * 5, "X", START, END), [])
            post.assert_not_called()


class FailureReportingTests(unittest.TestCase):
    def test_calendar_failure_is_explained_and_retried(self):
        import tempfile, pathlib
        from scraper import run
        page = mock.Mock(text="<html><title>Just a moment...</title></html>", url="u", headers={"content-type": "text/html; charset=utf-8"})
        class F:
            why = {}
            calls = 0
            def get(self, url):
                F.calls += 1
                return page
        src = {"name": "Cal", "type": "calendar", "url": "https://x/c.ics", "daily": True}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(run, "DATA", pathlib.Path(d)), \
                mock.patch("scraper.run.now", return_value=START):
            evs, st = run.calendar_events(F(), src, [], START, END)
            self.assertEqual(evs, [])
            self.assertIn("got text/html instead of a calendar file", st["error"])
            self.assertIn("Just a moment", st["error"])
            run.calendar_events(F(), src, [], START, END)
            self.assertEqual(F.calls, 2)  # the failed read was not saved as "done today"

    def test_blocked_request_reason(self):
        from scraper.common import Fetcher
        f = Fetcher(delay=0)
        f._robots["https://x.example"] = None
        resp = mock.Mock(status_code=403, headers={"server": "cloudflare"})
        resp.raw.read.return_value = b""
        with mock.patch.object(f.s, "get", return_value=resp):
            self.assertIsNone(f.get("https://x.example/c.ics"))
        self.assertIn("HTTP 403 from cloudflare", f.why["https://x.example/c.ics"])


class SourceReportTests(unittest.TestCase):
    def test_overlap_and_unique(self):
        from scraper.run import dedupe, normalize, source_report
        hn = {"id": "osm:1", "name": "High Noon Saloon", "kind": "bar", "website": ""}
        tap = {"id": "osm:2", "name": "Corner Tap", "kind": "bar", "website": ""}
        s = datetime(2026, 10, 30, 20, 0, tzinfo=TZ)
        a = normalize({"title": "Low Cut Connie", "start": s}, hn, "ticketmaster")
        b = normalize({"title": "Low Cut Connie", "start": s}, hn, "extra"); b["via"] = "Isthmus"
        c = normalize({"title": "Big Show", "start": s.replace(day=31)}, hn, "extra"); c["via"] = "Isthmus"
        d = normalize({"title": "Meat raffle", "start": s.replace(hour=15)}, tap, "weekly")
        out = dedupe([a, b, c, d])
        rep = source_report(out)
        self.assertEqual(rep["total_events"], 3)
        self.assertEqual(rep["in_more_than_one_source"], 1)
        tm, ist = rep["sources"]["Ticketmaster"], rep["sources"]["Isthmus"]
        self.assertEqual((tm["events"], tm["unique_events"], tm["overlap"]["Isthmus"]), (1, 0, 1))
        self.assertEqual((ist["events"], ist["unique_events"]), (2, 1))
        self.assertEqual(rep["sources"]["Weekly routines"]["unique_venues"], ["Corner Tap"])
