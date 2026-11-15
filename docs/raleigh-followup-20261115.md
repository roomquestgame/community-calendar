# Raleigh follow-up calendars and explicit weekly dates

Prepared November 15, 2026. This is the collector half of one batched release;
the private backend journal records enrollment and observed production results.
Capture counts below are source occurrences, not claims of unique physical
events or successful production publication.

## Remaining-source dispositions

| Source | Official calendar | Captured occurrences | Disposition |
| --- | --- | ---: | --- |
| ComedyWorx | <https://www.comedyworx.com/upcoming-shows> | 31 | Ready for enrollment |
| Chapel of Bones | <https://chapelofbones.com/events/> | 21 | Ready for enrollment |
| JC Raulston Arboretum children and workshops | <https://jcra.ncsu.edu/events/calendar/index.php> | 25 | Ready for supplemental enrollment |
| ShopSpace | <https://www.shopspace.org/classes> | 0 | Disabled: publisher-emitted Bookeo calendar path disallowed by robots |
| NOCO Brews & Bites | <https://www.nocobrewsandbites.com/community-events> | 0 | Disabled: native public calendar request returned HTTP 403 |
| Crooked Hammock Raleigh | <https://www.crookedhammockbrewery.com/locations/raleigh/events> | 0 | Disabled: anonymous event query returned GraphQL `unauthorized` |

No alternate calendar route, identity, cookie, proxy or robots exception was
attempted after those access failures. The Crooked Hammock result describes
that query only; it does not establish that the visible calendar requires login.
The eleven previously held sources were not retried or re-enabled.

## Full descriptions and locations

The existing shared HTML worker, source registration, record validation and
complete-only checkpoint machinery are reused. Two bounded display transports
are added for the exact publisher-emitted ComedyWorx Wix calendar and Chapel
TickPick organizer. They keep ordinary robots, DNS, pacing, timeout, size and
media checks, reject redirects, and cannot authorize arbitrary reads or writes.
The anonymous public Wix instance remains ephemeral and is not persisted.

All 77 accepted capture records retain their full published event body. Missing
or over-limit bodies are held with an explicit reason; bodies are never silently
shortened. This batch permits 12,000 characters for these exact new profiles.
ComedyWorx descriptions contain 305–904 characters, Chapel 67–969, and JCRA
1,235–2,215. The shortest Chapel description is its complete published text.

All 77 records have publisher-supported street addresses. ComedyWorx retains
each event's published suite and ZIP, plus its matching native point. Chapel
retains 658 Maywood Avenue, Raleigh, NC 27603 and uses the normal street geocoder.
JCRA retains 4415 Beryl Road, Raleigh, NC 27606; the backend binds this exact
source and venue to the existing publisher venue point rather than claiming
that the new HTML feed supplied coordinates.

See [performance source evidence](raleigh-followup-performance-evidence-20261115.md)
for pagination, exact public endpoints, native time conflicts and address proof.

## JCRA scope and schedule evidence

The healthy NC State Localist source already carries JCRA tours, lectures,
photography, Forest Bathing and Moonlight programs. The supplemental profile
selects native children-marked programs, workshops, Holiday Creations, and Art
and Blooms. It does not enroll the whole existing Localist calendar again.

The frozen 60-day replay starts November 15, 2026 at 13:00 UTC. It requires
complete November, December and January day grids plus the official visitor
hours page. Fifteen native entries resolve to eight public programs and 25 dated
occurrences; six sold-out entries and one invitation-only workshop are held.
The exact native Children's Program label is preserved on 24 occurrences as
publisher evidence. No classifier or forced category rules are changed.

Timed programs require agreement among the visible date, weekday, clock and
native calendar link. Self-guided StoryWalk and Yeti dates use explicit visible
date ranges, all corresponding native month-grid dates, and the published
seasonal opening hours. Incorrect midnight/range placeholders in downloadable
calendar exports are not treated as opening times. Explicit closure alerts
shorten the applicable day; unrecognized closure language holds self-guided
dates for review. Missing month cells, partial queues or unresolved schedules
cannot become a complete successful capture.

## Fairgrounds weekly recurrence

The already deployed N.C. State Fairgrounds source remains enrolled once at
<https://www.ncagr.gov/divisions/ncstatefair/events>. A fragment such as
`#Tab-October-21322` selects a tab in the same document; it is not another feed.

The recurrence parser expands `Every` followed by full weekday names joined by
commas, `and` or `&`. Expansion is confined to each row's published month and the
page's explicit year, then filtered through the existing upcoming 60-day window.
Every resulting date has the published local time in `America/New_York`, the
full event description and resolved Fairgrounds street address, with a stable
date-specific identity. Existing and repeated ingestion therefore does not
create another copy of the same source occurrence.

Explicit `CLOSED` date lists override matching weekly dates. Named month/day or
MM/DD dates can include a matching year and weekday. Closure notes are collected
across the same published year for the exact event title and native venue label,
so a January note can exclude a February date. The actual January 31 and
February 1, 2026 closure is parsed correctly. Conditional, ambiguous or
contradictory closure wording is held for review. Alternate-week, ordinal and
relative phrases are not guessed. A title merely mentioning weekly recurrence
does not create dates in other collectors.

The existing backend hides future public occurrences omitted by a completed
successful refresh after its publication queue drains. It does not invent a
cancelled status. Closure changes therefore depend on that normal refresh,
not an immediate edit notification. Partial or failed captures cannot trigger
cleanup. The generic five-minute stage freshness tolerance and normal handling
of already-started events remain unchanged.

The frozen Fairgrounds replay returns exactly the same 39 records and four
diagnostics as the deployed parser, including 13 upcoming Raleigh Market
occurrences. Its current page does not authorize inventing January 2027 dates
from January 2026 entries. No publisher refetch was needed for this fix.

## Focused verification and release boundary

The final local suite passed 127 tests covering the two new adapters, scoped
transports, shared worker, existing Raleigh transport and Fairgrounds recurrence.
Independent offline replay passed shared record, checkpoint and completion
validation for all 77 records. It also reproduced rejection of an incomplete
JCRA month grid and verified that adding native category evidence changed no
description, date, street or identity.

The accompanying JSON records code and evidence hashes without committing full
captured publisher bodies or public instance tokens. The backend batch must
still confirm actual production descriptions, streets, map points, held-source
status and cross-provider overlap. Routine GitHub test workflows are not run.
