# Raleigh fairgrounds, food, gaming and fitness calendars

Reviewed on November 15, 2026. These are newly implemented primary calendars;
none is a re-enrollment of a working published source. The separate Natural
Sciences repair and arts/nightlife/performance adapters have their own evidence.
The paused Visit Raleigh source is not requested or enabled by this module.

## Exact sources and research replay

| Source | Registered URL | Collection | Accepted occurrences | Held |
| --- | --- | --- | ---: | ---: |
| N.C. State Fairgrounds | https://www.ncagr.gov/divisions/ncstatefair/events | All twelve official monthly tables; explicit dates and daily hours | 39 | 4 ambiguous clocks |
| Goodnights Comedy Club | https://www.goodnightscomedy.com/events | The native Place/Event JSON-LD array, cross-checked against visible cards | 101 | 1 private closure |
| Our Giving Kitchen Raleigh | https://www.ogkraleigh.org/events | All upcoming Squarespace cards and full detail bodies | 2 | 0 |
| Transfer Co. Food Hall | https://transfer-co-food-hall.squarespace.com/upcoming-events | All upcoming Squarespace cards and full detail bodies | 9 | 1 conflicting month-long single-show range |
| Game Theory Raleigh | https://gametheorystore.com/calendar/ | Official embedded calendar and its public Raleigh-filtered event read | 24 | 97 missing descriptions; 3 closure announcements |
| Triangle Rock Club Salvage Yard — Run Club | https://account.trianglerockclub.com/salvage-yard/programs/run-club | Explicit publisher-declared Tuesday 5:30 PM schedule, next 28 days | 4 | 0 |

The six complete captured replays total **179 occurrences**. These counts are
offline research validation, not production publication. Snapshot anchors are
November 15, 2026, with a 60-day lookahead except the explicitly limited 28-day
Run Club schedule. Publisher closures, missing prose and unresolved clocks are
retained as diagnostics. Nothing is fabricated to fill those gaps.

All source tuples are `html/html`, timezone `America/New_York`. Each uses the
existing lease-fenced version-one checkpoint, at most 200 manifest units,
500 occurrences, 850,000 checkpoint bytes and a four-hour capture lifetime.
Ordinary preview-v2 staging runs only after a complete durable capture. No
per-source scheduler, special publication path or regional classifier is added.

## Full descriptions

Native HTML is cleaned once into paragraph-preserving text. Literal encoded
angle-bracket instructions survive. Empty descriptions are held. A description
over 12,000 characters is held with a visible limit diagnostic; it is never
silently clipped. Captured maximum lengths are 1,413 characters for fairgrounds,
3,002 for Goodnights, 1,091 for Our Giving Kitchen, 755 for Transfer Co., 53 for
Game Theory and 767 for the Run Club.

Goodnights supplies the full description of every individual show in its own
structured Event array. A visible single-show clock must agree with that exact
UTC instance. Multi-show cards link a series, so the explicit individual schema
instances supply those clocks. No invented end time is added.

Our Giving Kitchen and Transfer Co. list teasers. Every accepted item therefore
loads its canonical event detail and preserves `.eventitem-column-content`.
Detail title and structured start/end must agree with the listing's published
calendar-export timestamps. Google calendar links are parsed as text; Google is
not requested. An event incorrectly spanning a month is held rather than shown
as continuously ongoing. Detail processing resumes in groups of four.

Game Theory publishes short descriptions in its calendar data. These are the
entire native field, not an extraction truncation. The official shop event page
was also inspected: it supplies another calendar shell, with no longer prose
available in its public HTML. The adapter does not substitute a game title or
generic game rules for the 97 blank descriptions. Closing announcements are
excluded as non-events. The 24 accepted entries include actual TCG tournaments,
miniatures nights and an explicitly scheduled sale.

## Addresses and location provenance

| Source | Verified street | Evidence and scope |
| --- | --- | --- |
| Fairgrounds | 4285 Trinity Road, Raleigh, NC 27607 | Calendar footer supplies the campus address. Each event retains its named building or Outside Grounds; no separate building door is invented. |
| Goodnights | 401 Woodburn Road, Raleigh, NC 27605 | Event PostalAddress confirms street/city/state; official calendar header/footer provides ZIP. |
| Our Giving Kitchen | 225 South Wilmington Street, Raleigh, NC 27601 | Full event detail identifies The Shul Downtown and the exact street. |
| Transfer Co. | 500 East Davie Street, Raleigh, NC 27601 | Each detail's native event location must match the food hall. |
| Game Theory | 5910 Duraleigh Road Suite 125, Raleigh, NC 27612 | Official Raleigh location page: https://gametheorystore.com/raleigh/ . Only native `store_location=Raleigh` rows qualify. The suite remains in the street component for the shared structured-address parser. |
| Run Club | 2330 Salvage Yard Drive, Raleigh, NC 27604 | Official Salvage Yard program/community pages; required venue/address proof is still present in the fetched program page. |

These are reviewed publisher street bindings, not city-center coordinates.
Every row carries location evidence/provenance. The normal street geocoder
resolves their coordinates. No guessed latitude/longitude is supplied.

The fairgrounds calendar names the year explicitly. Recurring weekend market
dates are expanded only inside the published month/year. January 2027 is not
invented from the 2026 table. Weekday-specific and date-specific time clauses
select the corresponding daily opening hours. A bare `9-5` with neither AM nor
PM remains ambiguous and is held.

Run Club recurrence comes directly from “every Tuesday at 5:30pm,” with full
program prose. The next 28 days are refreshed by the ordinary collector. This
source covers that program only; it does not claim to ingest the gym's entire
booking calendar. The publisher supplies no end time, so none is invented.

## Narrow Game Theory public read

The official page embeds `https://gametheorystore.com/GT_WebCalendar.html`.
That public frontend declares its Supabase project and a **publishable** key.
The adapter extracts the current public key on each capture; no literal key is
committed, logged or stored in a checkpoint. Secret keys and privileged JWTs are
rejected. This public frontend grant is not a privileged database credential.

The worker permits only an HTTPS GET to that exact published project host's
`/rest/v1/events` path, with fixed selected columns, `store_location=eq.Raleigh`,
two bounded start-time filters, deterministic start/id order and limit 500.
Reaching that limit fails visibly. Arbitrary filters, hosts, paths, methods,
headers, old/future windows or combinations with other special transports fail
before I/O. The public key is attached only after independent validation and is
never forwarded on redirects. A fresh exact research request returned API 200;
the project robots endpoint returned 404.

Production still uses all normal DNS, robots, publisher pacing, deadline and
bounded-body checks. Research HTTP access does not prove access from Vercel.
Any production HTTP 403 or robots denial must disable the source and stop the
attempt, with no alternate identity or route.

## Verification

`tests/test_raleigh_direct_community.py` covers native full prose, visible/native
clock conflicts, explicit fairground weekdays, missing clocks, building
addresses, closure exclusion, exact public calendar identity, actual detail
hydration, complete-only replay, checkpoint mutation/expiry and the 28-day run
schedule. `tests/test_raleigh_direct_transport.py` covers the Game Theory GET
and Artspace public month POST, including exact form/query boundaries, public
key isolation, robots denial, HTTP 403, wrong content type and redirects.
`tests/test_raleigh_direct_worker.py` verifies the durable checkpoint precedes
full-description/street staging and that an unfinished empty listing cannot
masquerade as a complete calendar. The deployment receipt records final test
counts and actual production outcomes separately.
