# Raleigh direct nightlife and cooking calendars — 2026-11-15

## Scope and access evidence

These five sources are independent first-party calendars. None was already
registered in the municipal source registry at review time. Existing working
Raleigh sources and every existing hold are outside this change.

Public GETs from the research workspace used the collector's ordinary
`RoomQuestCommunityCalendar/0.2 (+https://roomquestapp.vercel.app/)` identity,
normal robots checks, bounded response bodies and publisher pacing. Their
calendar/API/detail samples returned HTTP 200 and permitted this identity in
robots.txt. Research access does not prove access from the production Vercel
environment. A production denial must remain a hold, without alternate
identities, proxies or challenge bypasses. No publisher consent or licensing
claim is implied by successful public access.

| Source key | Official calendar | Structured calendar | Verified venue |
| --- | --- | --- | --- |
| `neptunes_raleigh_nc` | https://www.neptunesraleigh.com/events | https://www.neptunesraleigh.com/events?format=json | Neptunes, 14 W Martin St, Raleigh, NC 27601 |
| `sports_social_cary_nc` | https://sportsandsocial.com/cary/events/ | https://sportsandsocial.com/cary/wp-json/tribe/events/v1/events | Sports & Social Cary, 301 Fenton Gateway Drive, Cary, NC 27511 |
| `slims_dive_bar_raleigh_nc` | https://slimsraleigh.com/calendar/ | https://slimsraleigh.com/wp-json/tribe/events/v1/events | Slim's Dive Bar, 227 S Wilmington St, Raleigh, NC 27601 |
| `hone_sharpen_raleigh_nc` | https://hone-sharpen.com/ | https://hone-sharpen.com/wp-json/tribe/events/v1/events | Hone-Sharpen, 516 N West St, Raleigh, NC 27603 |
| `cannonball_music_hall_nc` | https://www.cannonballmusichall.com/upcomingshows | https://events.humanitix.com/host/cannonball-music-hall | Cannonball Music Hall, 2304 Atlantic Ave, Raleigh, NC 27604 |

The exact deployed contract is HTML intake with `America/New_York`, complete
publisher descriptions up to 12,000 characters, and nullable coordinates sent
to the existing exact-street geocoder. Each venue address was verified on its
official page or native event schema. Explicit conflicting venue information
is held. Neptunes' Squarespace map fields contain a New York default point;
those fields are deliberately never treated as Raleigh venue coordinates.

## Calendar completeness and narrative handling

Neptunes exposes full event bodies and millisecond timestamps in its separate
`upcoming` array. The `nextPage` metadata paginates its `past` array: the observed
next offset page had 30 past events and zero upcoming entries. Upcoming events
are bounded by their native timestamps; title wording never generates dates.

Sports & Social exposes WordPress The Events Calendar REST and an official
`/cary/events/list/?ical=1` export. The adapter reads both the normal date-window
query and the overlapping-series query, validates all advertised pages and
stable totals, and consolidates identical occurrences. Its native long date
ranges describe recurring programs, not continuous events. Brunch, Monday
music bingo, Wednesday trivia and Tinsel are expanded only from their actual
published weekdays and clocks. Tinsel's Thanksgiving/Christmas closures and
holiday-eve hours override the weekly schedule. Unpublished bingo/trivia ends
remain null. Generic football-day entries without a clock are held. The two
native Wednesday trivia permalinks describe the same program and are
consolidated only while their complete normalized records agree.

Slim's official legacy calendar also advertises `calendar/?ical=1` and its
Tribe REST API. Many native descriptions are blank. Every otherwise eligible
blank description triggers a real official event-detail read; only a verified
matching event's `.tribe-events-content` can supply the missing narrative.
The observed Crow with No Mouth detail genuinely had an empty content block,
so its title or flyer is not substituted for prose. The separate newer
`slimsdivebar.com` Arkon calendar is not merged with the legacy feed or used to
guess different showtimes.

Hone-Sharpen exposes the same Tribe API and `events/?ical=1`. Its demonstration
kitchen and Hone-Sharpen venue names are bound to the official street address.
Private classes/events are excluded. Public classes preserve their complete
native descriptions. Tours with blank descriptions follow the same actual
detail-page check and hold behavior as Slim's.

Cannonball's official page embeds its Humanitix collection, and its official
FAQ links the exact Humanitix host page. Host JSON-LD provides the event
manifest; every unique detail page provides full visible
`.EventModuleRichText .RichContent` prose. The short JSON-LD teaser is never
substituted for that body. Detail JSON-LD arrays enumerate each series date,
including irregular days, and every in-window occurrence is retained.

## Processing and limits

`roomquest/raleigh_direct_nightlife.py` supplies the five exact profiles,
source-specific host allowlists and a resumable `collect_chunk` implementation.
All HTTP goes through the existing injected transport; this module contains
no HTTP client, identity override, browser/session path or script evaluation.

The capture window is 60 days anchored to immutable checkpoint `started_at`.
The checkpoint uses the existing version-one header and exposes pages as
manifest units, with a separate pending detail cursor. It expires after four
hours. A canonical payload checksum, native page totals, duplicate checks,
source/URL/venue validation and the existing lease boundary protect resumes.
Incomplete calls return no events. The normal staging path receives records
only after every page and detail disposition is complete.

Limits are 200 normalized records, 200 manifest units, four pages per Tribe
query, 850,000 stored checkpoint bytes and ten fetches per call subject to the
worker deadline. Overflow, changed pagination or conflicting duplicate records
raise visible errors. Descriptions longer than 12,000 characters are held in
full-description-limit diagnostics; they are never clipped and published.
Every missing/ambiguous description, unsupported schedule and conflicting
venue has a retained diagnostic with its native title and URL.

Focused tests cover source/URL scope, full descriptions beyond 2,000
characters, local/UTC agreement, private events, venue conflicts, real detail
hydration, absent prose, New York default geo rejection, all native Humanitix
series dates, holiday exceptions, partial checkpoints, duplicate/changed page
totals and visible overflow. No routine GitHub Actions workflow is dispatched.

### Captured-payload replay

The replay anchor was 2026-11-15 12:00 UTC. These are offline validation counts,
not a claim of production publication.

| Calendar | Complete normalized occurrences | Held | Final checkpoint size | Capture requests/chunks |
| --- | ---: | ---: | ---: | --- |
| Neptunes | 26 | 0 | 25,616 bytes | 1 / 1 |
| Sports & Social Cary | 63 | 3 without usable clocks | 125,005 bytes | 2 / 1 |
| Cannonball Music Hall | 18 | 1 with a genuinely blank detail description | 25,699 bytes | 13 / 2 |
| Slim's Dive Bar | 9 | 35 with genuinely blank detail descriptions | 18,846 bytes | 36 / 9 |
| Hone-Sharpen | 1 | 34 tours without a native detail description | 12,755 bytes | 35 / 9 |

The Cannonball replay included every current host-manifest detail page and all
native dates of Open Mic and Hijack Comedy. The held page was Death in the
Mountains Tour: its description container was empty, despite a listing teaser.
All accepted records retained complete cleaned native descriptions and the
verified full street address; no capture exceeded the checkpoint limit.

The final exact Slim's and Hone-Sharpen API queries each returned 47 native
rows. Slim's had 44 eligible in-window events: nine with full native prose and
35 requiring actual detail hydration. Hone-Sharpen had one eligible public
class with full prose and 34 tours requiring detail hydration; private and
out-of-window entries were excluded. All 69 missing-prose detail pages were
read through the ordinary robots-aware path and returned HTTP 200. Every
Slim's detail had an empty event-description block; every Hone tour detail
lacked a native event-description block. The final held counts therefore
reflect the actual complete detail capture, not an extrapolation from samples.

The Slim's Newspaper Taxis detail exposes the artist's Bandcamp website in
its Event JSON-LD `url`. A source-specific fallback proves the official page
through its exact canonical permalink, matching native WordPress post ID,
single matching schema title, visible title and occurrence start. The artist
website is never fetched. A regression rejects a changed canonical URL,
native ID, schema title or clock; the real empty description remains a hold.

These two replays used a four-fetch ticket budget, verified every resumed
checkpoint and never reread a completed prefix. Peak checkpoint sizes were
30,339 bytes for Slim's and 20,860 bytes for Hone, safely under the existing
850,000-byte limit. Slim's capture needed one bounded same-route resume after
an ordinary network timeout; no HTTP or robots denial occurred. All five
nightlife/cooking sources now have complete offline replay artifacts. The
focused nightlife, performance and neighboring Boston regression run passed
89 tests. Production access and publication remain separate checks.

The exact Sports overlap query was verified after correcting two legitimate
query details: WordPress rejects `1970-01-01 00:00:00` as a falsey epoch value,
so the historical lower bound is January 2, 1970; an explicit January
`end_date` would exclude a currently active trivia series ending in June, so
the overlap query uses `starts_before` and `ends_after` with the API's normal
future horizon. Both final exact query URLs returned HTTP 200.

## Other inspected venues and preserved holds

| Venue | Observed status | Follow-up |
| --- | --- | --- |
| Bond Brothers Eastside | Automatic approval review rejected the proposed Elfsight robots-parser adjustment as an access-control bypass. No endpoint content was fetched after rejection. | Keep disabled; do not retry with parser changes or alternate routing. This is an approval-review hold, not a reported HTTP 403. |
| Wolfe & Porter | Official page 200; the exposed Google calendar's public ICS route was robots-denied. The ICS body was not requested. | Keep feed disabled. |
| Crank Arm Brewing | Robots endpoint returned HTTP 202, preventing a valid allowed decision. | Keep source disabled pending an ordinary valid robots response. |
| Tin Roof Raleigh | Official calendar, public Gigwell scripts/settings/API and robots returned 200. The complete native result contained 82 rows, of which 80 were in the window and had full descriptions. | Implemented separately as `tin_roof_raleigh_nc` in `raleigh_direct_additional.py`, with the verified 300 Glenwood Ave, Raleigh, NC 27603 street and a complete replay. See the arts evidence document for the public query contract. |
| Chapel of Bones | Official calendar and TickPick widget script 200. The official organizer key is `chapel-of-bones`. | Inspect its exposed anonymous widget data contract before enabling. |
| Crooked Hammock Raleigh | Official calendar 200, but captured Popmenu HTML/Apollo state contains a calendar shell rather than event payloads. | Inspect its published calendar query; do not treat the shell as an empty complete calendar. |
| Fortnight Brewing | Official calendar, robots and both native R34ICS calendar displays returned 200. The complete Cary/Wake Forest displays contained 129 in-window entries, but event descriptions were absent or only runner emoji/a street address. | Keep `fortnight_brewing_nc` disabled with `publisher_event_narrative_unavailable`; no adapter or transport extension is enabled. This is a narrative-quality hold, not an HTTP denial. |

Visit Raleigh's production `publisher_http_403` hold remains unchanged. None
of these primary-source checks retries or bypasses that denied calendar.
