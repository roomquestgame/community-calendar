# Boston remaining nightlife, food and gaming sources — November 14, 2026

This is the second implementation cohort. It adds four previously unregistered
publishers found during the first discovery pass. Existing production sources and
the first ten-source nightlife cohort are excluded from these changes.

## Captured responses and completeness

The evidence JSON beside this document records every accepted occurrence's URL,
start/end, venue, full street address, description length, native description
SHA-256 and emitted-description SHA-256, plus every explicit hold. Ordinary public
responses were captured after reviewing each publisher's robots rules. The actual
collector delegates every network request to the existing guarded publisher
transport. Local `fetch_publisher` returns `dns_unavailable` before making a
request in this environment, so these replay results do not claim a completed
production ingestion. The batch deployment must confirm guarded runtime access,
geocoding, staging and final publication.

| New source key | Official collection surface | Accepted | Held or outside window | Durable chunks |
|---|---|---:|---:|---:|
| `eataly_boston_ma` | [Boston classes](https://www.eataly.com/c/classes-boston) and [Boston events](https://www.eataly.com/c/events-boston) | 76 | 31 outside the 60-day horizon | 23 |
| `trillium_brewing_ma` | [Trillium event calendar](https://trilliumbrewing.com/pages/event-calendar) | 34 | 4 missing descriptions; 1 missing venue/placeholder | 1 |
| `night_shift_brewing_ma` | [Night Shift events](https://nightshiftbrewing.com/events/) | 9 | 1 contradictory schedule | 1 |
| `waverley_oaks_park_ma` | [Waverley Oaks Park events](https://waverleyoakspark.com/events) | 46 | 0 | 10 |

All **165 accepted descriptions** equal the complete normalized native narratives
byte for byte, all 165 have structured street/city/state/ZIP values, and every
intermediate checkpoint passes the shared wire contract. Partial chunks emit no
events. Counts reflect the capture/replay timestamp in the JSON and change as the
rolling window advances.

## Eataly Boston: both catalogs, full product narratives and verified clocks

The new Eataly site exposes each catalog as a `CollectionPage` JSON-LD script.
Although the initially rendered card markup contains only a subset of products,
the JSON-LD lists the full page of twenty items. The collector reads six class
pages and the linked events catalog: 107 unique products in this capture. It
hydrates each product exactly once across durable chunks and preserves the full
`Product.description` together with the native descriptive lead, when distinct.
It never substitutes a product title or catalog excerpt for the narrative.

The product's inert React Router JSON stream contains typed `c_eventStartDate`,
`c_eventEndDate`, store, address and ticket-class fields. The decoder reads JSON
data without evaluating JavaScript. Native event identity and the selected
product's ticket-class identity must match; this also handles the chef's dinner
that has multiple ticket classes. Explicit UTC timestamps are retained.

The site's new visible renderer has a clock discrepancy that required an
independent publisher check. For [Hands-On: Tagliatelle alla Bolognese](https://www.eataly.com/p/hands-on%3A-tagliatelle-alla-bolognese-2002099885653.html),
Eataly's typed fields specify November 17, 2026, `20:00:00Z`–`21:00:00Z`, while its
rendered card shows 8–9 PM. The organizer-owned [Eataly Boston Eventbrite page](https://www.eventbrite.com/e/hands-on-tagliatelle-alla-bolognese-tickets-2002099885653)
visibly shows 3–4 PM and supplies JSON-LD `2026-11-17T15:00:00-05:00` through
`2026-11-17T16:00:00-05:00`. These represent the same instants as the typed Eataly
UTC fields. The product's typed UTC data is therefore corroborated by the
organizer's separate schedule. Eventbrite is research evidence; production
collection does not depend on it.

The native store/address fields and organizer page agree on **800 Boylston
Street, Boston, MA 02199**. The native point is retained as a reviewed venue
point. Products must identify the Boston store, a physical event, this exact
street/city/state/ZIP and a live event status. The 31 later products are held
outside the current sixty-day horizon and will enter later runs when eligible.

[Eataly robots](https://www.eataly.com/robots.txt) allow the public catalog/product
HTML routes. The implementation does not request `/action/`, `/resource/`,
transaction/account paths or robots-disallowed `/on/` media routes. Eataly images
on the latter route are deliberately left unimported.

## Trillium: official widget's native long descriptions

The official calendar embeds EventCalendarApp calendar `11960`, widget
`6336b28e-d559-413b-98dc-1e6ca65c95be`. The collector verifies those identifiers
on the publisher page, then uses the same public grid endpoint and epoch-second
window parameters used by the widget's public JavaScript. The endpoint returns
all 43 current records in one response; the normal list view would otherwise
page twelve at a time. The implementation requires a complete single grid page.

The collector maps `longDescription`, not `shortDescription`. It compares each
UTC timestamp with the widget's local timestamp under `America/New_York` or
`US/Eastern`, ensuring they identify the same instant. Closures are excluded.
Four winter-market records contain no native long description and remain held.
The holiday kickoff has no resolvable venue and placeholder detail, so it also
remains held. No description or location is inferred to make these publishable.

Venue streets come from Trillium's own location pages:

| Venue | Reviewed full address | Primary evidence |
|---|---|---|
| Trillium Canton | 100 Royall Street, Canton, MA 02021 | [Canton](https://trilliumbrewing.com/pages/canton) |
| Trillium Fort Point | 50 Thomson Place, Boston, MA 02210 | [Fort Point](https://trilliumbrewing.com/pages/fort-point) |
| Trillium Fenway | 401 Park Drive, Boston, MA 02215 | [Fenway](https://trilliumbrewing.com/pages/fenway) |

The separate [Headroom calendar](https://headroom.eventcalendarapp.com/), linked
from the official [Headroom page](https://trilliumbrewing.com/pages/headroom-hi-fi-lounge),
returned zero events in the same window. It is recorded as an empty current
schedule, without generating occurrences. Trillium and the public API's robots
responses permit the collection routes used here. No API credentials or private
routes are used.

## Night Shift: publisher-declared weekly rules and one dated lecture

The current [official calendar](https://nightshiftbrewing.com/events/) has four
cards with detail pages. All four are hydrated; listing excerpts are not used as
final descriptions.

- [Trivia](https://nightshiftbrewing.com/events/trivia-2/) explicitly declares
  every Monday, 7:30–9:30 PM.
- [Run Club](https://nightshiftbrewing.com/events/run-club/) explicitly declares
  every Saturday at 11:30 AM. Its current full narrative confirms the Saturday
  schedule. An older SEO excerpt still mentions Monday and is not used. The
  publisher gives no ending time, so `ends_at` remains null.
- [Lectures on Tap: How Great Stories Work](https://nightshiftbrewing.com/events/lectures-on-tap-how-great-stories-work/)
  explicitly lists Wednesday, November 18, 6:30–8:30 PM. The native article's
  publication year supplies 2026, and the weekday/date combination is validated.
- [Nerd Night](https://nightshiftbrewing.com/events/nerd-night/) is held. Its
  schedule field says Sunday, 4–9 PM, while the full native description and image
  label say 4–7 PM. Neither ending time is selected silently.

The user explicitly requested recurring venue schedules. The two unambiguous
weekly rules expand only within a rolling **28-day window**, with stable
occurrence identities, full native descriptions, `published_schedule` and
`schedule_provenance=publisher_declared_weekly_schedule`. Recognized titles and
exact clock/weekday rules must continue to agree with current detail pages.
Visible closure/cancellation statements cause a hold. This replay yields four
Trivia occurrences, four Run Club occurrences and the dated lecture.

The official site supplies **87 Santilli Highway, Everett, MA 02149** for the
Everett Taproom. Coordinates are left pending the existing shared geocoder.
[Robots](https://nightshiftbrewing.com/robots.txt) prohibit the WordPress JSON
routes; only ordinary permitted HTML is collected.

## Waverley Oaks Park: dated tenant calendars, including Mighty Squirrel

Waverley Oaks Park is the property/venue operator and publishes its own tenant
events. Its [dated event calendar](https://waverleyoakspark.com/events) includes
Mighty Squirrel's Crokinole and board-game gatherings, runs and trivia, plus
restaurant specials, workshops, the library bookmobile and athletic-club events.
This gives a permitted ordinary-HTML source for Mighty Squirrel's Waltham
programming. The separate Mighty Squirrel Wix calendar was investigated, but its
embedded data path is not needed to ingest these confirmed dated events.

All 46 upcoming cards hydrate the full Squarespace event-detail content. The
collector checks title, start/end and venue agreement between the listing and
detail, then validates the native map address against the reviewed venue.
Only explicit dated cards are ingested; weekly dates are not inferred here.

| Native venue | Reviewed full address |
|---|---|
| Mighty Squirrel Brewing Co. | 411 Waverley Oaks Road, Waltham, MA 02452 |
| City Streets Restaurant | 411 Waverley Oaks Road, Waltham, MA 02452 |
| Birdie Bar | 411 Waverley Oaks Road, Waltham, MA 02452 |
| Waverley Oaks Athletic Club | 425 Waverley Oaks Road, Waltham, MA 02452 |

The calendar also contains past Beaver Brook Reservation events with the native
address 66 Mill Street, Belmont, MA 02478; no past occurrences are imported. All
Waverley coordinates remain pending the existing shared geocoder.

[Robots](https://waverleyoakspark.com/robots.txt) disallow Squarespace JSON and ICS
query exports. Only ordinary event HTML and reviewed native image URLs are used.
The calendar does not establish coverage of Mighty Squirrel's separate Fenway
venue, which remains outside this source's stated scope.

## Engineering and validation

`boston_nightlife_remaining.py` reuses the first cohort's native description,
timezone and Squarespace helpers and the standard record builder. It provides
the existing module contract (`SOURCES`, `LABELS`, hosts, diagnostics, source
notes, `collect` and `collect_chunk`). No shared transport or parser defaults are
changed. A page manifest plus per-page detail cursor preserves progress across
five-fetch chunks. The original start time is immutable; checkpoints expire
after four hours and reject more than sixty seconds of future skew. Complete
rows and the pending manifest are hashed; changed source manifests reset the
collection. All four sources stay within the normal 200-event and 900-KB bounds.

Nine focused regressions cover complete catalog enumeration, ticket variants,
UTC clocks, full narratives and blank-description holds, durable partial output,
mutation detection, four-hour expiry, Trillium clock agreement, declared weekly
rules without assumed end times, conflicting schedules, detail hydration and
URL/route restrictions. The captured full-source replay additionally verifies
all accepted description hashes and all intermediate shared wire boundaries.
No routine GitHub diagnostic workflow was dispatched.
