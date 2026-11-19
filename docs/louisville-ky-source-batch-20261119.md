# Greater Louisville — first-party source expansion canary (November 19, 2026)

**Scope:** Louisville/Jefferson County plus Bullitt, Oldham, Shelby, Spencer and nearby communities; expand across all nine event ecosystems and surrounding localities. This is batch 01, **not a final coverage report**. EventQuest's configured radius remains at most 100 miles.

## Existing production baseline — read-only
- The Louisville metro row (`public.community_areas.id=23`) is staged, not automatically a live published-metro proof.
- 49 future-dated `external_events` rows explicitly mentioning a Louisville venue/address at this audit: JCC of Louisville 44, Locust Grove 3, Riverside Landing 2. These are historical collector results **not newly added** and not a deduplicated public card count.
- Existing approved first-party registrations include Bernheim (WordPress), JCC, Locust Grove, Riverside Landing, Louisville Zoo (iCalendar, **unchecked**), and Shelbyville Kentucky city events (iCalendar, last success October 28, 0 future). Speed Art Museum remains paused/disabled; preserve this hold. Do **not** confuse Shelbyville IN or Jefferson County IA/CO/MO with Kentucky.
- Live Louisville Zoo first-party `https://louisvillezoo.org/events/?ical=1` returned HTTP 200 `text/calendar`, 8 VEVENTs, seven (or fewer) with a published zoo location; one December Birthday Bash has no LOCATION/GEO. This existing registration must first be refreshed through normal protected source demand and checked for event-level addresses; never substitute the zoo's center for an unlocated event.

## Four newly verified native Bullitt County Library branch iCalendars
A short-lived Vercel sandbox using explicitly allowlisted publisher hosts fetched each publisher's `robots.txt` (HTTP 200, no feed-path disallow), exact iCalendar feeds (HTTP 200, `text/calendar`), and the publisher's current branch selector. It followed no publisher-blocked path, used no credentials, and did no data writes. Source snapshot date November 19, 2026. An unfiltered feed has 763 VEVENTs extending as far as 2040, so **never use it for ingestion**. The official `start` and `end` parameters limit the pull to 60 days.

| Source key | Branch | Native branch ID | Official original street | Observed correctly located 60-day publisher VEVENTs |
| --- | --- | --- | --- | ---: |
| `bullitt_library_shepherdsville_ky` | Central Library, Shepherdsville | 87 | 740 Conestoga Parkway, Shepherdsville KY 40165 | 78 |
| `bullitt_library_lebanon_junction_ky` | Lebanon Junction Branch | 124 | 11382 S. Preston Highway, Lebanon Junction KY 40150 | 38 |
| `bullitt_library_mt_washington_ky` | Mt. Washington Branch | 121 | 214 N. Bardstown Road, Mt. Washington KY 40047 | 72 |
| `bullitt_library_west_point_ky` | Nichols Branch, West Point | 123 | 10729 Highway 44 West, West Point KY 40177 | 23 |
| **Total** | Four branches, four publishers' official filters | | | **211 pre-ingestion rows** |

Canonical stable URLs follow:
`https://bullittcounty.librarycalendar.com/events/feed/ical?branches%5B87%5D=87`, analogous branch IDs 124, 121, 123. At collection time append `&start=<YYYY-MM-DD>&end=<YYYY-MM-DD>` to fetch the rolling publisher-supported 60-day window. The publisher supplies 4 distinct street/GEO pairs, original event URLs, UTC DTSTART and DTEND, descriptions (one centrally located preview lacks prose; preserve a legal empty fallback), categories, and recurrence instances. No ATTACH image was present in the scoped sample; do not fabricate imagery. Samples include Nov 19 Toddler Storytime (Central), Nov 19 Louisville Ballet's Nutcracker Storytime (Lebanon Junction), Nov 19 Active 55+ (Mt. Washington), Nov 19 Gifts of Gratitude (Nichols). Branch filter results still include shared blank-location events: those must **never** be mapped to a branch source center. Hillview's closed branch is excluded.

The strict per-source collector implementation holds absent/offsite location, inconsistent native GEO, unverified event detail link, private/closure records or unclassifiable publisher evidence, and preserves original event text. This snapshot's **211** is *not* a completed parser acceptance count, registered source count, published card count, or public-search visibility receipt. Record each milestone separately.

## Other nine-ecosystem queue and blockers
1. **Libraries/education:** Louisville Free Public Library `https://events.lfpl.org/events/list` publishes current dated events. Proposed common LibraryMarket ICS route timed out twice; **not validated**, do not enroll on guessed URL. Oldham County Public Library `https://www.oldhampl.org/events?month=11&year=2026` live HTML, custom platform and event-level full street/adapter need review. Shelby County libraries, Jefferson community colleges and university departments next.
2. **Arts/music:** `https://www.kentuckyperformingarts.org/events` first-party live dated concerts; backend exporter/structured parser still requires evaluation. Kentucky Shakespeare, Actors Theatre, Speed Art Museum (existing paused; do not activate arbitrarily), Brown Theatre and smaller venue calendars next.
3. **Nightlife/social:** `https://gravelybrewing.com/events` displays dated recurring music and trivia. Determine event detail API, original event timezone and venue per event before registration. Fourth Street Live `https://4thstlive.com/en/` has current date-stamped nightlife listings; discover venue-specific original first.
4. **Outdoor/active:** Bernheim already exists; investigate Louisville Metro Parks/Jefferson Memorial Forest, The Parklands of Floyds Fork, Floyd County and state parks. Do not infer program dates from recurring hours.
5. **Food & drink:** brewer-owned official schedules, food markets, winery tours and culinary classes; avoid venue-only or private booking pages.
6. **Sports/recreation:** Louisville Bats, Louisville City FC, Racing Louisville FC, school/college event owners; preserve actual dates and event venue.
7. **Family/gaming:** Four verified library branches above, museums, zoo, local game stores and family recreation centers; preserve event categories and kid/adult evidence.
8. **Markets/festivals/nonprofits:** farmers/holiday markets, food banks, volunteer and association calendars; publisher-origin events preferred to aggregator copies.
9. **Civic:** Louisville Metro `https://louisvilleky.gov/government/city-events` lists Dec 5 Light Up Louisville but other dated 2026 items are already past. Discover official calendar endpoints and route appropriate notices to separate Civic Hub with proper jurisdictions; no generic Events injection.

Tourism `https://www.gotolouisville.com/events-calendar/` and `https://louisvilledowntown.org/event-search/` are *lead indexes*, not authority for duplicate syndicated publication.

## Deployment and next checkpoint
- New collector module `roomquest/bullitt_library_branches.py` and a source-key-specific branch in `roomquest/preview_worker.py` are limited to the four exact official feeds. No new scheduler, no publisher guessing or sitewide crawl, no GUI changes or DB writes.
- Run focused no-network tests `tests/test_bullitt_library_branches.py` and bounded first-party collector transport before merge. Honor the existing owner rule against routine GitHub Actions CI; do not incur separate Actions per source.
- After collector code is tested and Vercel READY, use **only protected GitHub database deploy**, never direct Supabase writes, to register each complete approved source with exact URL, America/New_York, event collection, geocoder eligibility, coverage-selection-only coordinates, no rights assertion, and normal demand. Preserve PG17 squash and existing source records.
- Inspect real `municipal_event_sources`, `community_staged_events`, `external_events`, geocoding and public Events search after demand; deduct cross-branch duplicates and exclude closures. Do not mark production deployed or public visible without receipts.
- Next discovery: Louisville Free Public Library feed performance, Oldham PL native events export, Kentucky Performing Arts structured events, Jefferson/Shelby/Spencer libraries, Metro Parks and official recurring nightlife feeds.
