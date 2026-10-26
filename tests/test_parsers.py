"""Run with: python -m unittest discover -s tests"""
import unittest
from datetime import datetime, timedelta

from scraper import extract as X
from scraper.common import TZ
from scraper.ical import parse_ics
from scraper.run import categorize, dedupe, expand_recurring, normalize
from scraper.venues import apply_overrides, kind_of

START = datetime(2026, 10, 26, 12, 0, tzinfo=TZ)  # a Monday
END = START + timedelta(days=14)
VENUE = {"id": "osm:node/1", "name": "Test Tap", "kind": "bar", "address": "1 Main St", "website": "https://t.example",
         "lat": 43.0, "lon": -89.4, "facebook": ""}

ICS = """BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:trivia@t\r
DTSTART;TZID=America/Chicago:20260901T190000\r
DTEND;TZID=America/Chicago:20260901T210000\r
RRULE:FREQ=WEEKLY;BYDAY=TU;UNTIL=20261231\r
EXDATE;TZID=America/Chicago:20261103T190000\r
SUMMARY:Tuesday Trivia\\, hosted by Pat\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:trivia@t\r
RECURRENCE-ID;TZID=America/Chicago:20261027T190000\r
DTSTART;TZID=America/Chicago:20261027T200000\r
DTEND;TZID=America/Chicago:20261027T220000\r
SUMMARY:Halloween Trivia\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:band@t\r
DTSTART:20261031T020000Z\r
DURATION:PT3H\r
SUMMARY:The Long\r
  folded Band\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:old@t\r
DTSTART:20250101T020000Z\r
SUMMARY:Old show\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:fest@t\r
DTSTART;VALUE=DATE:20261107\r
DTEND;VALUE=DATE:20261108\r
SUMMARY:Fall Fest\r
END:VEVENT\r
END:VCALENDAR\r
"""


class ICalTests(unittest.TestCase):
    def test_parse(self):
        evs = parse_ics(ICS, START, END)
        titles = sorted((e["start"].strftime("%m-%d %H:%M"), e["title"]) for e in evs)
        self.assertEqual(titles, [
            ("10-27 20:00", "Halloween Trivia"),           # moved instance replaces 7pm one
            ("10-30 21:00", "The Long folded Band"),       # 02:00 UTC on the 31st is 9pm Central
            ("11-07 00:00", "Fall Fest"),
            # 11-03 trivia is excluded by EXDATE
        ])
        trivia_1110 = parse_ics(ICS, START + timedelta(days=14), START + timedelta(days=16))
        self.assertEqual([e["title"] for e in trivia_1110], ["Tuesday Trivia, hosted by Pat"])
        # DST ends Nov 1: weekly 7pm stays 7pm local
        self.assertEqual(trivia_1110[0]["start"].hour, 19)


class PageTests(unittest.TestCase):
    def test_jsonld(self):
        html = """<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
          {"@type":"MusicEvent","name":"Cool &amp; Band","startDate":"2026-10-30T20:00:00-05:00",
           "offers":{"price":"10.00"},"location":{"@type":"Place","name":"Test Tap"},"url":"/shows/cool"},
          {"@type":"Event","name":"Cancelled thing","startDate":"2026-10-31T20:00",
           "eventStatus":"https://schema.org/EventCancelled"},
          {"@type":"Organization","name":"Not an event"}]}</script>"""
        evs = X.jsonld_events(html, "https://t.example/events")
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["title"], "Cool & Band")
        self.assertEqual(evs[0]["price"], 10.0)
        self.assertEqual(evs[0]["url"], "https://t.example/shows/cool")
        self.assertEqual(evs[0]["start"].hour, 20)

    def test_gcal_and_ics_and_links(self):
        html = """<a href="/events/">Events</a><a href="/menu">Menu</a><a href="https://facebook.com/x/events">FB</a>
        <a href="webcal://t.example/cal.ics">Subscribe</a><a href="/live-music">Music</a>
        <iframe src="https://calendar.google.com/calendar/embed?src=abc%40group.calendar.google.com&amp;ctz=America%2FChicago"></iframe>"""
        s = X.soup_of(html)
        self.assertEqual(X.candidate_pages(s, "https://t.example/"),
                         ["https://t.example/events/", "https://t.example/live-music"])
        self.assertEqual(X.ics_links(s, "https://t.example/"), ["https://t.example/cal.ics"])
        self.assertEqual(X.gcal_feeds(html),
                         ["https://calendar.google.com/calendar/ical/abc%40group.calendar.google.com/public/basic.ics"])

    def test_tribe_and_squarespace(self):
        tribe = {"events": [{"title": "Euchre &#8211; League", "start_date": "2026-10-28 18:30:00",
                             "end_date": "2026-10-28 21:00:00", "cost": "Free", "url": "https://t.example/e/1"}]}
        e = X.tribe_events(tribe)[0]
        self.assertEqual((e["title"], e["price"], e["start"].hour), ("Euchre – League", 0.0, 18))
        sq = {"upcoming": [{"title": "Open Mic", "startDate": 1793149200000, "fullUrl": "/events/open-mic"}]}
        e = X.squarespace_events(sq, "https://t.example/events")[0]
        self.assertEqual(e["url"], "https://t.example/events/open-mic")
        self.assertEqual(e["start"].tzinfo, TZ)

    def test_weekly_text(self):
        html = """<p>Tuesdays: Trivia at 7pm</p><p>Friday Fish Fry 4:30 - 8:30 p.m.</p>
        <p>Meat Raffle every Saturday at noon</p><p>We love Mondays</p><p>Karaoke 9pm</p>"""
        got = [(w["activity"], w["days"], w["time"]) for w in X.weekly_from_text(html)]
        self.assertEqual(got, [("trivia", [1], "19:00"), ("fish fry", [4], "16:30"), ("meat raffle", [5], "12:00")])


class ShapingTests(unittest.TestCase):
    def test_categorize(self):
        self.assertEqual(categorize("Friday Fish Fry"), "food")
        self.assertEqual(categorize("Music Bingo"), "music")
        self.assertEqual(categorize("Bingo Night"), "bingo")
        self.assertEqual(categorize("Packers watch party"), "sports")
        self.assertEqual(categorize("Mystery"), "other")

    def test_recurring_and_dedupe(self):
        rec = [{"venue": "Test Tap", "title": "Fish Fry", "days": [4], "time": "16:30", "minutes": 240,
                "category": "food", "price": 15}]
        evs = expand_recurring(rec, {"test tap": VENUE}, START, END)
        self.assertEqual([e["start"][:10] for e in evs], ["2026-10-30", "2026-11-06"])
        scraped = normalize({"title": "Fish fry: walleye", "start": datetime(2026, 10, 30, 17, 0, tzinfo=TZ),
                             "end": None}, VENUE, "scraped")
        out = dedupe(evs + [scraped])
        self.assertEqual(sorted((e["start"][:10], e["source"]) for e in out),
                         [("2026-10-30", "scraped"), ("2026-11-06", "weekly")])

    def test_venue_kinds_and_overrides(self):
        self.assertEqual(kind_of({"name": "VFW Post 7591", "amenity": "bar"}), "veterans")
        self.assertEqual(kind_of({"name": "Madison Elks Lodge", "amenity": "social_club"}), "lodge")
        self.assertEqual(kind_of({"name": "Bean", "amenity": "cafe"}), "cafe")
        vs = [dict(VENUE), {**VENUE, "id": "osm:node/2", "name": "Closed Bar"}]
        out = apply_overrides(vs, [{"match": "Test Tap", "website": "testtap.com"}, {"match": "Closed Bar", "skip": True},
                                   {"name": "Back Room", "kind": "bar", "website": "https://br.example"}])
        self.assertEqual([(v["name"], v["website"]) for v in out],
                         [("Test Tap", "https://testtap.com"), ("Back Room", "https://br.example")])


if __name__ == "__main__":
    unittest.main()
