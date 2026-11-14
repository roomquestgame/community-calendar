# Boston remaining community sources — November 14, 2026

Four remaining profiles produced **300 complete records** in captured-response
replay. Every record passed the shared Boston description and street gate. The
real worker functions, with only publisher transport and database RPC calls
replaced by captured responses/in-memory receipts, staged the same 300 records
without changing descriptions, addresses, identities or dates. No incomplete
checkpoint staged any records. These are implementation and replay results;
production verification belongs to the deployment receipt.

| Source | Registry scope | Accepted occurrences | Collection | Full description length |
|---|---|---:|---|---:|
| Boston College | Repair paused, empty source 4318; preserve its key and feed URL | 76 | Four complete Localist pages | 60–2,560 characters |
| Rose Kennedy Greenway | New official calendar | 70 | 71 dated detail pages; 24 durable chunks | 55–1,684 characters |
| Mass Audubon Boston Nature Center | New official program calendar | 21 | 25 program details; nine durable chunks | 913–1,274 characters |
| Boston Cares | New public volunteer calendar | 133 | One public calendar display POST | 1,064–3,030 characters |

## Full native descriptions and actual dates

Boston College reuses the Localist format, retaining the complete native
`description` field rather than the legacy facts-only adapter. The collector
requires published, public, physical or hybrid entries with explicit timed
instances. Empty prose, prose equal to the title, `TBD`/`Research summary`
placeholders, undated all-day entries, and unresolved away venues remain held.
Several native sports descriptions are brief title-plus-ticket/broadcast facts;
they are retained as published and are not expanded with invented prose.

Greenway's Events Manager monthly calendar supplies dated manifest entries.
Each entry is paired with its complete Elementor event body and explicit local
start/end values in its add-to-calendar link. Listing excerpts ending in `[...]`
and shortened export descriptions are never used as the event description.
The Google link is parsed locally as metadata; Google Calendar is not fetched.
Undated recurrence previews outside the rendered calendar are not converted
into events from their URL names. Duplicate dates shown in adjacent monthly
grids are deduplicated by native event URL and identity.

Mass Audubon's JSON-LD description is a teaser. The collector instead preserves
the complete visible Description, native instructions, audience and admission
sections. Each explicitly listed session becomes its own occurrence. The
60-day bound excludes later sessions without inventing a recurrence. For
example, the winter Nature Year series has a December session at Squantum Point
Park, January at Boston Nature Center and a later February session. The
unresolved December meeting point is held, January is retained at the sanctuary,
and February remains outside the current collection window.

Boston Cares' public JavaScript calendar uses the anonymous display endpoint
`https://www.bostoncares.org/search/getOpportunitiesCalendar`. Its three POST
fields are `searchvo_startfrom`, `searchvo_endfrom`, and fixed
`searchvo_searchresultblockid=589`. The response is JSON served with
`Content-Type: text/html; charset=utf-8`. Its full native `description` is
preserved; the site's client-side 200-character preview clipping is not used.
Only explicit, still-open physical occurrences in the reviewed Boston metro
localities are selected. The inclusive 14-calendar-day window is November
14–27 in this capture. Future refreshes move that bounded window forward.

No collector invents a description, time, recurrence, attendance fee or audience
attribute. The existing classifier receives the full evidence through the
normal pipeline; this change does not modify category rules.

## Street and point resolution

The collector uses each event's actual venue. A generic publisher headquarters
is never substituted for an off-site event.

Boston College's official Localist place directory resolves named campus
buildings, while official BC facility directions resolve campus access streets
where a building has no numbered event address. Those access-address venue
labels identify their scope explicitly. Conflicting native geocodes are left
for normal geocoding: Trinity Chapel's visible 883 Centre Street differs from
its 885 geometry, Stuart House's visible 899 differs from 885, Robsham's native
postal codes disagree, and Alumni Stadium has different visible and geometric
street numbers. The complete reviewed street is retained in each case.

Greenway's Carousel uses its published 191 Atlantic Avenue address. Dewey
Square Plaza uses the official venue page's 600 Atlantic Avenue. Armenian
Heritage Park's own directions give 115 Atlantic Avenue, corroborated by the
Greenway venue's Boston 02110 postal information.

Boston Harbor Distillery's Greenway beverage garden is **not** the producer's
Dorchester distillery. Its official venue page identifies High Street and
Atlantic Avenue; its linked map explicitly targets latitude 42.3566833,
longitude -71.0507724. This is the single reviewed non-numbered street
exception. The common gate requires the exact source, venue, street and point.
The map's separate viewport coordinates are not used.

Mass Audubon meeting instructions override reusable park metadata. Castle
Island's JSON-LD says 2010 Day Boulevard, while the actual meeting instructions
say Sullivan's parking lot, **2080 William J Day Boulevard**. The record uses
the meeting address. Millennium Park uses the stated canoe-launch parking
meeting address at 300 Gardner Street. Native center metadata is never applied
to a walk whose narrative explicitly places it in Milton or Quincy.

Boston Cares addresses require exact serving organization, activity title and
publisher ZIP agreement with a reviewed actual venue. Native prose provides
Ellis Jamaica Plain's 555 Amory Street, East End House's 105 Spring Street, FCC
Revere's 230 Beach Street and other streets directly. The American Red Cross
pantry's native description contains an incorrect 02128 ZIP, while its native
calendar locality/ZIP and the Red Cross's official pantry page agree on
1033 Massachusetts Avenue, Boston 02118; only the structured venue address is
corrected and the original full prose remains intact. Fresh Truck's operator
publishes actual mobile-market sites in its November 2026 schedule. Those
streets are matched to each named market; volunteer dates and times still come
from Boston Cares' dated instances, and no generic Fresh Truck headquarters
is used.

The machine-readable evidence records every accepted event's identity, full
street, description length/hash, provenance and location evidence URL.

## Remaining holds and access limits

| Item | Why it remains held |
|---|---|
| Greenway horticulture volunteer project | Meeting location varies along the park and is supplied separately after registration. |
| Mass Audubon fall Belle Isle/Winthrop walk | The detail page does not publish its actual meeting entrance. |
| December Nature Year session and Squantum Point Park walk | Actual park is known, but the published parking directions lack a verified numbered meeting address. |
| Jamaica Plain duck walk | A Pond Avenue parking lot is specified without a verified numbered meeting point. |
| Neponset River walk | Narrative explicitly says Milton; reusable location metadata instead names a Boston street. |
| Nine Boston Cares occurrences | Specific Food Link, HiSET tutor and Washington Beech market locations are not sufficiently resolved; no organizational headquarters is substituted. |
| Esplanade embedded Google Calendar | `calendar.google.com` robots disallows the calendar/ICS paths. No alternate-host workaround or access bypass was used. |

Local execution of the production `fetch_publisher(..., respect_robots=True)`
and the new fixed Boston Cares renderer failed at `dns_unavailable` before an
HTTP request in this workspace. Ordinary unauthenticated research captures
succeeded. The production worker must therefore confirm live guarded transport
after deployment; captured replay does not claim to have cleared that gate.

## Durable and worker verification

Greenway's complete checkpoint is 182,862 bytes; Nature Center's is 55,827 bytes.
Both remain below the shared 900,000-byte wire bound and 200-event source limit.
The immutable dated manifest, exact source, UTC start time, Eastern window date,
four-hour expiry, processed prefix, per-outcome row hash and full record bodies
are checked on resume. Three detail reads are attempted per chunk. No partial
event array is returned for staging.

The real worker replay made 24 Greenway checkpoint writes and nine Nature Center
writes. Boston College and Boston Cares completed as ordinary collectors.
Every final description and address matched the direct collector output
exactly. Only mocked RPC receipts were used; this verification made no database
writes.

Focused validation passed **63 tests and 49 subtests** across the community
modules, Boston worker integration and remaining-source transport. Checks cover
complete prose beyond 2,000 characters, title/placeholder rejection, public
eligibility, actual street binding, time disagreement, pagination completeness,
checkpoint expiry/tampering, complete-only staging, exact POST window and the
follow-up B1 coordinate corrections. The only warning is an existing pytest
plugin deprecation.

### Principal evidence URLs

- [Boston College public calendar/API](https://events.bc.edu/api/2/events)
- [Boston College venue directory/API](https://events.bc.edu/api/2/places)
- [BC recreation facility directions](https://www.bc.edu/bc-web/offices/rec/about/facilities/directions.html)
- [Greenway calendar](https://www.rosekennedygreenway.org/calendar/)
- [Armenian Heritage Park directions](https://www.armenianheritagepark.org/directions-parking)
- [Boston Harbor Distillery's Greenway location](https://bostonharbordistillery.com/pages/bhd-at-the-greenway)
- [Boston Nature Center programs](https://www.massaudubon.org/programs/boston-nature-center)
- [Boston Cares calendar](https://www.bostoncares.org/calendar)
- [Red Cross Boston Food Pantry](https://www.redcross.org/local/massachusetts/about-us/our-work/food-and-nutrition-programs.html)
- [Fresh Truck official weekly-market page](https://www.freshtruck.org/pages/weekly-markets)
- [Fresh Truck November 2026 schedule linked by that page](https://cdn.shopify.com/s/files/1/0582/7896/9428/files/November_26.pdf?v=1793643796)
