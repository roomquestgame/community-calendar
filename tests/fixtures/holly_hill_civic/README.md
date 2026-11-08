# Holly Hill civic calendar capture and contracts

Captured from public publisher responses on 2026-11-08. No authentication,
cookies, member records, signup forms or account metadata are included. These
fixtures establish parser behavior, not deployed worker or publication success.
The collector uses the existing protected transport supplied by its caller.

## Sources and sanitization

* `santee_calendar.html`: the complete 68-entry Event ItemList from
  `https://www.santeecoopercountry.org/daily-events-calendar/`, extracted from the
  root agent's `/tmp/hollyhill-scc.html` capture. Site navigation, scripts and
  tracking are omitted. Event data, list positions and declared count are kept.
  The retrieved occurrence times reflect the publisher's updated 12:30 p.m.
  Orangeburg tour and 4 p.m. Eutaw Springs oyster roast.
* `beidler_night.html`, `beidler_family.html`, `beidler_boo.html`: canonical link,
  page title, Beidler center identity link and actual `nas_full_width_text`
  sections from the three registered Audubon seasonal pages. Signup forms,
  tracking and global navigation are removed. Event schedule years, weekdays,
  times and factual prose are unchanged. The scenic hero photos are deliberately
  not occurrence-specific image candidates.
* `sc250.json`: a public TEC probe of
  `https://southcarolina250.com/wp-json/tribe/events/v1/events?per_page=100&start_date=2026-11-08&end_date=2027-01-07&page=1`.
  It advertises 41 results but returns 33 objects. Original-response SHA-256:
  `5d7d9d730f7c0b79680abf62dd4f96dfebfebe565573e8f3a7ca08f391627c91`.
  Author metadata, unrelated publication fields, organization contacts and image
  renditions are removed. Counts and event fields are retained. This is a
  regression fixture for the JSON recurrence/completeness problem, not the
  registered production route. Per-page 20 returned 35 unique objects across
  three pages; per-page 10 returned 37 across five pages. The missing records
  are not safely recoverable by ignoring the reported total.
* `sc250_calendar.ics`, `ics_page2.ics`, `sc250_ics_page3.ics`: the actual public
  exports at `https://southcarolina250.com/events/?ical=1`,
  `https://southcarolina250.com/events/list/page/2/?ical=1`, and
  `https://southcarolina250.com/events/list/page/3/?ical=1`. Each contains 30
  VEVENTs; the HTML calendar page stride is 12, so adjacent exports overlap by
  18 unchanged occurrence UIDs. The third export reaches January 27, 2027,
  beyond the reviewed 60-day window. UID, exact start/end, timezone, title,
  description, venue, event URL, attachment and categories remain unchanged.
  Organizer email and per-event creation/modification/stamp metadata are removed.
  These exports expose nine distinct weekly Ken Burns occurrence records from
  November 11 through January 6, rather than one collapsed series entry. Their
  descriptions explicitly restrict the program to April and May, so all nine
  receive `publisher_series_month_conflict` holds until that evidence agrees.
* `eutawville.json`: valid `events: []`, `total: 0`, `total_pages: 0` from
  `https://townofeutawville.gov/wp-json/tribe/events/v1/events` with the same
  November 8–January 7 query window. Empty here is a successful publisher result.
* `elloree.json`: the 18-entry bare-array result of the official calendar's
  documented read-only POST `{}` to
  `https://connect.elloreesc.com/api/functions/getPublicCalendarEvents`.
  Public record IDs, schedules, descriptions, location labels and imagery remain;
  `created_by`, author IDs and administrative timestamps are removed. The page
  also supports the `{data: [...]}` wrapper, covered by a shape test. Raw-response
  SHA-256: `1a505b4aa7b76d781da9969b70e5a33f5575e1c429340e031afd6044afa19b55`.

## Time and venue contracts

All five sources use the reviewed `America/New_York` display timezone. SCC
requires actual offset-bearing timestamps. TEC must agree on local and UTC
representations. ICS requires publisher timezone data. Elloree and the explicit
Beidler prose schedules use the reviewed local zone; ambiguous/nonexistent DST
wall times fail instead of receiving an invented offset. Date-only and local
midnight placeholders are not converted into timed public events.

Beidler's three scoped programs explicitly take place in its swamp/boardwalk.
Its official visitor evidence is
`https://www.audubon.org/beidler-forest/visit`; the reviewed venue is Audubon
Center at Beidler Forest, 336 Sanctuary Road, Harleyville, SC 29448. Elloree's
exact `Elloree Town Hall` venue label maps to the official town address at
`https://elloreesc.com/`: 2719 West Cleveland Street, Elloree, SC 29047. Neither
mapping supplies coordinates. Other Elloree location labels are held, not moved
to Town Hall. SCC may retain a publisher event's own finite South Carolina
coordinates only alongside that event's complete street/city/state address.

## Holds and completeness

The Crosswind Farm anniversary occurrence is explicitly held because its full
publisher detail says Saturday November 15 while its schema says November 15,
2026 (Sunday). Its exact source link is in `SANTEE_REVIEW_HOLDS`; the truncated
listing alone cannot resolve that conflict. D&G's SCC midnight occurrence is
held; no direct-business time is silently substituted into the tourism record.
SC250's Ken Burns series has a separate explicit month conflict: recovering
distinct ICS occurrence IDs does not establish that the stale recurring series
actually runs in those months. The unchanged fixture produces nine month holds;
a separate mutation test proves recovery only when publisher prose agrees.

Cancelled/virtual/private records and town-office closures are excluded.
Unknown venues, placeholder starts and contradictory schedules produce named
holds. A source with only held eligible records is an evidence failure, not a
healthy empty result. Past explicit schedules can yield a healthy empty without
rolling the year forward. Incomplete/malformed lists and changed pagination
fail the snapshot. No source-center pins or synthetic events are used.

SC250's final source URL is the ICS URL, `kind=ical`, `platform_adapter=ical`.
`collect_sc250_ics` validates the shared ICS shape and merges publisher UIDs only
after proving ordered, exact overlap or a genuine terminal export. It stops once
the last ordered occurrence reaches the collection horizon, or an export has
fewer than 30 entries, with a five-page deadline/size ceiling. It never registers
the demonstrably incomplete JSON probe as a complete source.

Other civic discoveries remain in `PENDING_SOURCES` with explicit hold reasons,
including World Grits' April 2027 dates outside the current window and RecDesk's
unimplemented public program listing. They are not empty-success parsers.
