# MadisonPulse reference sheets

Rebuilt automatically after every scrape (about 6 am and 6 pm). Click a file to see it as a
searchable table on GitHub, or use the download button to open it in Excel or Google Sheets.

| File | What's in it |
| --- | --- |
| restaurants.csv | Every restaurant the planner can suggest: cuisine, price estimate, alcohol, menu link, weight |
| bars_venues.csv | Bars, breweries, VFWs, lodges, venues, coffee shops: event feeds we read, events found, alcohol |
| activities.csv | Bowling, pool, arcades, movies and similar |
| events.csv | Every event in the next two weeks: category, price (listed or estimated), link, which sources found it |

**Weights** live in `data/weights.csv` (one level up). Change the `weight` column to steer
suggestions: 1 = normal, 1.5 = more often, 2 = a lot more, 0.5 = less often, 0 = never.
`event title` rows match any event whose title contains that text. New places are added at 1
after each scrape; numbers you change are never overwritten. The site picks up an edited
weights file within a couple of minutes.

**Where things come from**
- Places: OpenStreetMap (national chains left out), refreshed weekly.
- Alcohol: an OpenStreetMap tag, a name/type rule (e.g. "tavern", "brewery", juice bars), or an
  AI read of the place's own website.
- Menu links: OpenStreetMap's menu tag, or the "Menu" link on the restaurant's homepage
  (checked monthly). Without one, the site links a Google search for the menu.
- Pictures: the image each place or event page publishes for link previews (what shows when
  it's shared on Facebook or in a text), from their own site, the event feed or Ticketmaster.
  Shown from their site, never copied; nothing from Isthmus.
- Events: venue websites and calendars, the Isthmus city calendar (facts only), Ticketmaster,
  and AI reading of venue event pages. "all sources" lists every source that had the event.
