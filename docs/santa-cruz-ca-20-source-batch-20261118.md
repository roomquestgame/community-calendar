# Santa Cruz, California — 20-source batch 2 (November 18, 2026)

**Batch contract:** one branch, a target of **20 distinct publisher sources**, grouped under one coherent collector PR. No production enrollment until individual feeds pass identity, exact venue, date/time, complete publisher narrative, media-rights and recurrence checks. Never force 20 unverified sources to satisfy a numerical target.

## Validation snapshot — 6 active collectors, 14 held/under review

The 20-source research roster is accounted for. **Six publishers have working guarded collector dry runs** on this branch, while the other 14 have documented holds, blockers or unverified formats. All 6 active sources have complete publisher narrative and event-specific numbered streets, subject to normal database geocoding.

| Source | Verified dry-run candidates | Native coordinates | Image candidates | Format |
| --- | ---: | ---: | ---: | --- |
| Woodhouse Blending & Brewing | 6 | 0 | 6 | First-party JSON |
| Discretion Brewing | 23 | 0 | 22 | First-party dated HTML |
| Santa Cruz Museum of Natural History | 9 | 0 | 9 | TEC REST JSON |
| Rio Theatre | 7 | 7 | 7 | Squarespace JSON |
| Game Night Collective | 13 | 0 | 0 | Calendar ICS |
| Visit Santa Cruz County | 118 | 115 | 47 | TEC REST JSON (secondary) |
| **Total** | **176** | **122** | **91** | |

Regressions: **20 focused tests passed** (14 existing UCSC/Kuumbwa/Woodhouse/Discretion tests plus 6 new museum/tourism/Rio/Game tests) and all six publishers were separately dry-run through `preview_worker.preview_source`. The source-level checks are not claims of staging or production publication. No new database migration or ongoing crawl jobs are introduced by the collector PR. **The remaining 14 sources are not declared working or enrolled** merely to meet the 20-source roster requirement.

### Additional discovery decisions

- **Moe's Alley**: official TicketWeb calendar has show times but no event narratives in the list, and robots advertises 10-second crawl delay. Individual shows require safe detail checkpointing; no title-only records.
- **Pajaro Valley Arts**: `https://pvarts.org/events/?ical=1` returns 50 VEVENTs dated **2023**, not upcoming in 2026. Do not import.
- **Felton Music Hall**: 53 Webflow Event JSON-LD records, only two future in the tested window; schema gives date but not show time, and both descriptions on the calendar are generic venue boilerplate. Hold until verified richer first-party event details.
- **Rio Theatre** was substituted for speculative Humble Sea recurrence in roster slot 8. Humble Sea remains follow-up-only.
- **The Game Night Collective** syndicated ICS contained conflicting Capitola Library street numbers and The Cruz Room at an unrelated 1001 Center Street. These cannot be used as location evidence; exact verified venue filters hold them.

The original two sources, **UC Santa Cruz** and **Kuumbwa Jazz**, are **not** included in these 20: their preceding collector PR #264 and backend migration #1183/#1187 are already production deployed. Do not recreate the three existing Santa Cruz Public Libraries Mapsee ICS registrations.

## Batch 2 source roster (exactly 20)

| # | Source / official first-party page | Coverage | Feed and quality status |
|---:|---|---|---|
| 1 | [Woodhouse Blending & Brewing](https://www.woodhousebrews.com/calendar) | Concerts, DJs, art, markets | **Adapter coded and live dry run passed**: public JSON `https://www.woodhousebrews.com/api/events`; 6 accepted, 6 full descriptions, 6 street-verified, 6 image candidates. Original event links on the publisher's Squarespace subdomain. Bodyless teaser events held; no guessing from JavaScript fallback |
| 2 | [Discretion Brewing](https://www.discretionbrewing.com/events/) | Live music, trivia, film, markets | **Adapter coded and live dry run passed**: matched date/time HTML detail cards; 23 accepted, 23 full descriptions, 23 street-verified, 22 publisher image candidates. Blank/unparseable schedules and closures held. No working TEC or ICS alternate found |
| 3 | [Moe’s Alley](https://moesalley.com/calendar/) | Live music and community benefits | **Held**: 10 upcoming TicketWeb listing cards provide show times/links but no narratives; full detail requires event-scoped fetches with 10-second robots delay. Need bounded continuation to avoid incomplete snapshots |
| 4 | [The Catalyst](https://catalystclub.com/events/) | Music, comedy, club nights | Live dated listings with age restrictions, prices and distinct show times; use official venue detail records; check Ticketmaster duplicates |
| 5 | [The Cruz Room](https://cruzroom831.com/events) | Concerts, bluegrass jams, trivia, pinball, board games | Live event page with rich descriptions and dated occurrences; use venue source identity and filter closure notices; check overlapping Game Night Collective and Ticketmaster entries |
| 6 | [The Game Night Collective](https://gamenightcollective.com/santa-cruz-events) | Board games, RPGs, playtesting | **Collector ready**: public iCalendar 147 VEVENTs. Guarded dry run accepts **13** events only at explicitly verified Gilman Brewing, The Cruz Room, Peoples Coffee and 11th Hour addresses with unique event links and full descriptions; conflicting library and moved-venue addresses held |
| 7 | [11th Hour Coffee](https://www.11thhourcoffee.com/pages/events) | Trivia, coffee, workshops | Official recurring trivia and workshops page; verify future dated occurrences, not stale Oct 2026 announcements |
| 8 | [Rio Theatre](https://www.riotheatre.com/events-2) | Film, concerts, theater, comedy | **Collector ready**: first-party Squarespace JSON `/events-2?format=json`; 7 accepted upcoming, all own 1205 Soquel Ave street, 7 native coordinates, full narratives and 7 image candidates; offsite/undated and postponed records held |
| 9 | [Bookshop Santa Cruz](https://bookshopsantacruz.com/events) | Author talks, signings, book clubs | Official calendar with full event venues, including **offsite events**. Collector request returned HTTP 403; do not bypass. Offsite book readings also appear in UCSC calendar; dedupe |
| 10 | [Santa Cruz Museum of Natural History](https://santacruzmuseum.org/events/) | Nature walks, volunteer programs, classes | **Collector ready**: first-party WordPress Events Calendar REST JSON; 10 publisher records / 9 accepted with full narratives, own venue street and 9 image candidates. UTC+0 configured listing held for timezone review |
| 11 | [Santa Cruz Museum of Art & History](https://www.santacruzmah.org/) | Exhibitions, archives, talks, First Fridays | Dated event page; publisher transport HTTP 403. Hold until approved accessible feed or publisher authorization |
| 12 | [Santa Cruz Art League](https://scal.org/) | Art classes, exhibition receptions | First-party exhibition and reception schedule. Validate venue/date specifics per program and avoid recurring daily exhibit cards without actual visit program |
| 13 | [Santa Cruz Beach Boardwalk](https://beachboardwalk.com/events-and-entertainment/) | Festivals, holiday attractions, film, concerts | Current official dated programs and multi-date winter events. Venue/attraction-specific admission and schedules need event-detail extraction. Avoid duplicating individual Ticketmaster shows |
| 14 | [City of Santa Cruz Parks & Recreation](https://www.santacruzca.gov/Government/City-Departments/Parks-Recreation/Recreation-Events-Calendar) | Workshops, sports, markets, municipal events | Rich official future calendar with cancellation markers; HTTP 403 from collector network. Need approved calendar feed, not bypass |
| 15 | [Santa Cruz County Parks](https://parks.santacruzcountyca.gov/Home/FindaProgram/CommunityEvents.aspx) | Outdoor tours, recreation, volunteering | Official county community program listings. Inspect calendar iframe/API for dated events before enrollment |
| 16 | [Tannery Arts Center](https://www.tanneryartscenter.org/events/) | First Friday open studios, seasonal art market | First-party page lists regular First Friday and Dec. 12 Winter Art Market. `/events?format=json` responds, but its collection contains **zero usable upcoming event items**. No speculative recurrence without event-level location/time evidence |
| 17 | [Santa Cruz Shakespeare](https://santacruzshakespeare.org/) | Theatre performances, readings | Dec. 2026 *A Christmas Carol* has published show times at **Veterans Memorial Building, 846 Front St**, not outdoor summer Grove. Verify separate performances and seasonal venues |
| 18 | [Santa Cruz Community Farmers Markets](https://santacruzfarmersmarket.org/markets/) | Food and neighborhood markets | Publisher confirms Downtown Wed., Live Oak Sun., Westside Sat. year-round and seasonal Scotts Valley/Felton. **Markets at intersections must not be assigned invented street numbers**; use reviewed intersection/verified coordinates or hold |
| 19 | [Santa Cruz Area Chamber](https://web.santacruzchamber.org/cwt/external/wcpages/wcevents/eventsstartpage_n.aspx) | Business networking, workshops, mixers | Official legacy Chamber calendar with dated entries. Verify event-specific street and detail completeness; not merely Chamber office address |
| 20 | [Visit Santa Cruz County](https://www.santacruz.org/events/) | Countywide events, nature, museums, markets | **Collector ready**: 17-day bounded first-party publisher TEC REST JSON; 118 accepted with complete text/numbered event streets; 115 publisher coordinates, 47 photo candidates. **Secondary aggregator**, dedupe/publication require backend review |

## Collector test receipts, not production counts

On branch `feat/santa-cruz-venues-woodhouse-discretion-20261118`, exact `preview_source` dry runs through the guarded collector's robots/DNS/host network path returned Woodhouse **6** and Discretion **23** events, with **0 blank descriptions** and verified own venue streets. Seven focused unit tests passed. The accepted Woodhouse images were 6 original CDN candidate URLs (the `format=750w` thumbnail modifier is stripped); Discretion accepted 22 first-party image candidates. **No publisher photo rights or public event publication are claimed by these counts.**

## Release strategy

Within the 20-source branch, build/validate viable sources in coherent source-adapter groups; keep blocked or undated sources explicit as **held research**, never silently register them. Use shared EventQuest categories and event-specific identities; fix positive/near-miss trigger lessons where warranted. Before this branch merges, verify all included collectors with explicit host approvals, payload size/pagination/deadline budgets, healthy unit fixtures and real publisher dry runs. Production admission remains one deliberate forward-only backend migration per cohesive batch, preserving the 2026-11-17 PG17 baseline, existing category workers, serving workload, exact venue geocoding and public Events/Map/Home display.

The 20-source target is **not** currently 20 active collectors: first two adapters are implemented; the other 18 are researched and require individual validation. No new source enrollments, migrations, cron jobs or production event records are introduced by this source roster.
