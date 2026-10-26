# MadisonPulse

Plan a night out in Madison, WI. Five questions (budget, group size, vibe, cocktails, dinner/show) build a night from local spots, and the next 14 days of events come from bars, VFW and Legion posts, lodges, coffee shops, breweries and venues that the big calendars miss.

## How it works

```
OpenStreetMap ──► data/venues.json ──► scraper visits each venue website ──► data/events.json ──► site/
   (weekly)         (+ venue_overrides)     (every 4 hours)                    (+ recurring.json)
```

1. **Venue list** (`scraper/venues.py`, weekly): every bar, pub, café, brewery, VFW, Legion, Eagles/Elks/Moose lodge, community center and venue in the Madison area from OpenStreetMap, with websites where OSM has them.
2. **Event scrape** (`scraper/run.py`, every 4 hours): for each venue website it finds and reads
   - iCal (`.ics`) feeds and subscribe links
   - embedded Google Calendars (very common on VFW, Legion and small-bar sites)
   - WordPress "The Events Calendar" API
   - Squarespace event pages
   - schema.org Event data (Wix, Eventbrite widgets, most CMSs)

   Each site's sources are remembered in `data/venue_sources.json` and re-checked weekly.
3. **Weekly routines** in `data/recurring.json` (fish fry, meat raffles, bingo, trivia) fill in the many places that never post dates online. A scraped listing for the same night replaces the weekly one.
4. **GitHub Actions** (`.github/workflows/scrape.yml`) runs all of this, commits the data, and publishes `site/` to GitHub Pages.

## Optional sources (off until you add a key)

Add keys under repo **Settings → Secrets and variables → Actions → New repository secret**. The next scheduled run picks them up.

| Secret | What it turns on | Cost |
|---|---|---|
| `TICKETMASTER_KEY` | Ticketed shows at the Majestic, High Noon, Sylvee, Orpheum and other Ticketmaster venues | Free key from developer.ticketmaster.com |
| `ANTHROPIC_API_KEY` | Claude reads venue pages that list events as plain text (about 4 in 5 venue sites) | Pay as you go; capped at `AI_MAX_CALLS` pages per run (default 60), unchanged pages are not re-sent |

## Places in plans

- **Shows** are always real events from the scraper; there are no stand-in venues.
- **Dinner, bars and late-night food** come from `data/restaurants.json` and `data/venues.json` (OpenStreetMap, refreshed weekly) plus the hand-picked list in `site/spots.js`. They're chosen by walking distance from the event, and opening hours are respected where OpenStreetMap has them.

## One-time setup

1. **Turn on Pages:** repo Settings → Pages → Source: **GitHub Actions**.
2. **Run it the first time:** Actions → "Scrape events and publish site" → Run workflow (tick *Re-pull the venue list*).
3. The site appears at `https://dwoods4032.github.io/MadisonPulse/`.

## Files you edit

**`data/recurring.json`** — weekly events. Days are 0 = Monday … 6 = Sunday.

```json
[
  {"venue": "VFW Post 7591", "title": "Friday Fish Fry", "days": [4], "time": "16:30", "minutes": 240,
   "category": "food", "price": 15, "note": "Cod, perch or walleye", "confirm_url": "https://facebook.com/..."},
  {"venue": "Some Bar", "title": "Meat Raffle", "days": [5], "time": "15:00", "weeks": [1, 3]}
]
```
`weeks` limits to those weeks of the month (1st and 3rd Saturday above). `skip_dates` takes `["2026-12-25"]`. Categories: music, trivia, karaoke, bingo, comedy, open_mic, food, dance, sports, other.

**`data/venue_overrides.json`** — fix or add venues. Match by OSM name or id.

```json
[
  {"match": "Le Tigre Lounge", "website": "https://example.com"},
  {"match": "Closed Bar", "skip": true},
  {"name": "Back Room at Somewhere", "kind": "bar", "address": "123 Main St", "website": "https://..."},
  {"match": "Some Cafe", "feeds": [{"type": "ical", "url": "https://.../calendar.ics"}]}
]
```
Kinds: bar, brewery, veterans, lodge, cafe, venue, library, community.

**`data/sources.json`** — calendars not tied to one venue website:
`[{"name": "Library", "venue": "Central Library", "kind": "library", "type": "ical", "url": "https://..."}]`
(`type`: ical, jsonld, tribe, squarespace)

## Files the scraper writes

| File | What it is |
|---|---|
| `data/events.json` | Everything in the next 14 days, read by the site |
| `data/report.json` | Per-venue results: which sources were found, how many events, errors |
| `data/weekly_suggestions.json` | Lines like "Tuesdays: Bingo 6:30pm" found on venue sites. Review and copy good ones into `recurring.json` |
| `data/venue_sources.json` | Cached event sources per venue |

## Run locally

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -t .
python -m scraper.venues
python -m scraper.run --limit 25
cd site && cp -r ../data . && python -m http.server
```

## Ground rules the scraper follows

- Identifies itself (`MadisonPulseBot`) and obeys each site's robots.txt.
- At most one request per site every 1.5 seconds.
- Reads venue websites and public calendar feeds only. It does not scrape Facebook or Instagram.
