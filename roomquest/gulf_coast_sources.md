# Gulf Coast calendars discovered through The Event Quest

Owner-approved intake, reviewed November 14, 2026. The Event Quest archives are
discovery leads; refreshes read the current organizers' public calendars.

## Reviewed routes

All routes use the existing `html/html` collector, `America/Chicago`, guarded
publisher transport, a 60-day window, v3 publisher evidence and shared publication.
The backend enrollment is committed in RoomQuestGame migration
`20261114193905_gulf_coast_eventquest_sources.sql`.

| Source key | Organizer calendar | Captured-page occurrences | Scope |
| --- | --- | ---: | --- |
| `gulf_walter_anderson_ms` | https://www.walterandersonmuseum.org/events | 5 | Complete Wix event list; actual event venues |
| `gulf_new_orleans_track_club_la` | https://www.runnotc.org/event-list | 2 | Complete Wix race list; Rivertown has no precise start pin |
| `gulf_rapahope_al` | https://www.rapahope.org/fundraising | 1 | Normal HTML index and event detail; no donation-card campaign |
| `gulf_crescent_city_markets_la` | https://crescentcityfarmersmarket.org/our-markets | 2 | Only the explicitly dated Uptown and Mid-City occurrences |
| `gulf_gallery_night_fl` | https://gallerynightpensacola.org/2025-dates/ | 2 | Visible edition year and verified local hours; corridor location awaits resolution |
| `gulf_maple_leaf_la` | https://www.mapleleafbar.com/calendar | 16 | Complete Wix event list; preserve separate shows |
| `gulf_nola_christmasfest_la` | https://nolachristmasfest.com/plan-your-visit/ | 18 | Explicit admission sessions, including December-to-January rollover |
| `municipal_mapsee_d871199cc551aa175f82de2b` | https://neworleanscitypark.org/calendar/ | 16 | Repair existing source 4585 with venue-bearing listing JSON-LD |
| `gulf_national_wwii_museum_la` | https://www.nationalww2museum.org/events/events-calendar | 41 | Explicit museum-campus filter; timed physical events only |
| `gulf_tipitinas_la` | https://tipitinas.com/calendar/ | 27 | Validated backup; all captured occurrences already covered by Ticketmaster/TicketWeb |

Counts describe captured publisher pages, not new public rows. Publication still
requires the source's reviewed production snapshot, eligible event facts, a
verified venue, shared classification and actual demand. Tipitina's stays paused
to avoid duplicating its existing provider coverage.

## Identity, timing and venue decisions

- The Crescent overview and City Park calendar both list the City Park farmers
  market. City Park's explicitly dated weekly series is authoritative. The
  Crescent parser validates all three cards but emits only Uptown and Mid-City.
- City Park's exact `arts-market-new-orleans-holiday-market` series is already
  covered by the primary Arts New Orleans iCal source
  `municipal_mapsee_123326fd5be1b9af7ecaaf9b`. It is omitted from this secondary
  calendar; the November 14 audit matched both December 12/13 occurrences.
- Wix parsers require a complete public widget (`hasMore: false`), published
  scheduled events, explicit timestamps, the reviewed timezone and matching
  event address/coordinate fields. Featured widgets are not complete calendars.
- Rapahope's robots rules disallow its JSON/ICS format queries. Only its normal
  HTML is used. The event-owned OpenGraph address must agree with Event JSON-LD.
- Gallery Night's URL still says 2025, while the visible edition is 2026. Its
  published local 5–9 p.m. schedule governs; the homepage UTC countdown does not.
- ChristmasFest imports separate printed sessions. It neither invents daily
  opening hours from a festival range nor uses the Calliope rideshare entrance
  as the venue. Its main venue is the Morial Convention Center, Halls G–I.
- City Park's REST and ICS feeds omit venues. Its public list pages contain
  complete Event JSON-LD. Date-only ranges, the conflicting Celebration in the
  Oaks range and sponsor-only Merry Maker Mixer are withheld. Public board
  meetings remain subject to the shared Civic classifier.
- WWII Museum collection verifies the applied museum-campus filter and excludes
  virtual, offsite and date-only cards. It traverses chronological pages through
  the window, failing if the bounded traversal cannot finish.
- Tipitina's uses show time, not doors. Multi-night ticket bundles do not create
  additional attended events. Missing end times remain unknown.
- No collector copies source coverage coordinates into events. Address-only
  occurrences use the existing venue resolver. District/corridor records stay
  unpinned until the resolver has sufficient evidence.

## Sources held outside this release

| Lead | Reason |
| --- | --- |
| Hattiesburg Saenger | Normal collection receives a SiteGround CAPTCHA |
| Gulfport Harbor Lights | Organizer and ticket page disagree on closing date/hours; format exports disallowed by robots |
| Family Gras | 2027 dates and venue confirmed, timed schedule not yet established |
| MoonPie Over Mobile | Current lead lacks a sufficiently accessible automated schedule |
| French Quarter Festival | 2027 dates announced; available daily hours still describe 2026 |
| New Orleans Jazz Fest | 2027 date blocks announced; detailed music schedule remains the prior edition |

## Verification and release

Focused local checks cover publisher identity, complete pagination, venue
evidence, conflicting schedules, session identity, timezones, robots-aware
dispatch and the existing publisher-evidence regression suite:

```sh
python -m pytest -q tests/test_gulf_recurring.py tests/test_gulf_seasonal_sources.py tests/test_gulf_venues.py tests/test_publisher_evidence.py
```

The workspace's guarded live transport reports `dns_unavailable`; captured
public HTML validates parsers but is not production transport proof. Production
previews must be checked after the collector release and backend registration.
Keep sources pending until that readback passes, enable only reviewed sources,
and verify real `external_events` rows and category/location outcomes afterward.
No routine CI, new scheduler or alternative publisher is introduced.
