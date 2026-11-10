# Civic collector publisher captures

Captured directly from the official public sources listed in `provenance.json`.
The fixture fingerprints refer to the complete original response. Fixture HTML
retains the parser-relevant publisher nodes, with page chrome, JavaScript,
forms, and the Commonwealth request-verification token removed. All 72
Commonwealth rows and all 10 DMV first-page rows are retained. Legistar JSON
retains all returned records with only the mapped factual fields.

The fixed replay time is November 9, 2026, 10:00 UTC. These replay counts are
parser evidence, not claims of database publication or verified venue pins.

## Source scopes

- `richmond_va_legistar`: the city's official Council Meetings page links to
  `https://richmondva.legistar.com/Calendar.aspx`. The documented API is
  `https://webapi.legistar.com/v1/richmondva/events`. The captured bounded
  November 9–January 8 request returned 13 meetings.
- `alexandria_va_legistar`: the city's Dockets & Webcasts page links to the
  corresponding official Legistar calendar. The API is
  `https://webapi.legistar.com/v1/alexandria/events`; five meetings were returned
  by the same bounded request.
- `virginia_commonwealth_calendar`: the default root page publishes a current
  seven-day window, November 9–16 in this capture. GET date-filter parameters
  did not change that window, so the collector requests only the published root
  and does not claim a 60-day statewide snapshot. The embedded Google calendar
  template attributes carry the publisher's exact date offsets, narrative and
  event-specific location. They are parsed locally; Google is never requested.
- `virginia_dmv_connect`: only the default first page is collected. It advertises
  10 of 15 upcoming visits. Publisher robots permits this page but disallows
  its query and pagination routes and sets a 30-second crawl delay. The shared
  transport retains that delay; no pagination endpoint is requested.
- `clarksville_municipal_notices_va`: the official town's `/news/` first page,
  with all 12 cards preserved. Its November 11 office closure is supported by
  the exact article at `/7444-2/` and explicit November 12 reopening text.
  Publication dates and unbounded leaf-collection announcements are not event
  dates or household schedules. Clarksville replay time is November 10 at
  12:00 UTC; one notice is eligible.
- `south_hill_public_works_va`: sanitized official public-works page evidence
  reviewed November 10 UTC, containing only the published third-Wednesday
  bulky-item rule and its request/booking requirement. This is not a household
  trash-route schedule; no household applicability is inferred.

Robots responses for Commonwealth and Legistar were 404. DMV robots was read
before requesting its allowed unfiltered listing. Normal collector transport
continues to revalidate publisher access and pacing, independently of fixtures.

## Factual boundaries

The Legistar CLI's guessed two-hour duration is not used. Unknown meeting times
are held. Source timestamps are interpreted in each registered source's explicit
timezone. Only the exact Richmond council-room alias uses the independently
documented address at `https://www.rva.gov/office-city-clerk/council-meetings`;
other rooms retain their own published location for the shared venue resolver.

Commonwealth marks three board/committee meetings as All Day without resolved
structured start times. These three are held as `commonwealth_meeting_time_unresolved`;
69 of the 72 raw rows are eligible at the fixed replay time. Truly non-meeting,
explicit date windows use `civic.kind=window` and exclusive `ends_on` dates.
UTC midnight bounds are transport/query bounds, not invented appointment times.
Their source timezone remains attached.
The Culpeper transportation meeting demonstrates why the actual event location
must be used: the site's map link and contact address incorrectly point toward
Richmond, while its event template and detail prose identify 1601 Orange Road
in Culpeper. Cancellation is read only from an explicit publisher status;
absence from a bounded page is never cancellation evidence.

DMV descriptions retain appointment restrictions and midday lunch closures.
No fees, free-service claims, household applicability, polling locations or
service-area geometry are inferred. No image capability, new timer, separate
publication pipeline or external comment/subscription action is introduced.
