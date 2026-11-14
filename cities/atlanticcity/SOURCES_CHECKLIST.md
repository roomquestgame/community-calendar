# Atlantic City source discovery and implementation — November 14, 2026

## Scope and production baseline

Ben authorized broad local discovery, full-description ingestion, street-address resolution, batched PRs and production deployment, including Visit Atlantic City. Production inspection found no registered Atlantic City-area community sources; the initial 15-mile future-event sample contained 126 Ticketmaster events. Existing working sources are outside this change. Nearby county calendars are included, while event coordinates always identify actual venues.

## New source batch

| Publisher | Core coverage | Collection path | Address resolution |
| --- | --- | --- | --- |
| [Anchor Rock Club](https://www.anchorrockclub.com/events-calendar) | Nightlife, music, film, markets | Reviewed public HTML/API | 247 S New York Avenue, Atlantic City, NJ 08401 |
| [Atlantic City Arts Foundation](https://atlanticcityartsfoundation.org/calendar) | Arts, public art, community | Reviewed public HTML/API | Event-specific; current mural: 167 South Tennessee Avenue, Atlantic City, NJ 08401 |
| [City of Atlantic City](https://www.acnj.gov/calendar) | Civic meetings, neighborhood events, community meals | Reviewed public HTML/API with durable continuation | City Hall or the actual named event venue; one explicitly labeled numbered-block estimate |
| [Atlantic City Free Public Library](https://acfpl.org/events-menu/library-event-calendar-menu.html) | Learning, family, gaming, crafts, community | Reviewed public HTML/API | Main: 1 North Tennessee Avenue; Richmond: 4115 Ventnor Avenue, Atlantic City, NJ 08401 |
| [Atlantic County Library System](https://atlanticcounty.librarycalendar.com/events/feed/ical) | Learning, family, gaming, makers, community | Native ICS | Publisher branch directory and event-specific offsite streets; never a system headquarters |
| [Caroline's By The Bay](https://carolinesnj.com/specials) | Trivia, music bingo, social | Reviewed public HTML/API | 450 Bay Avenue, Somers Point, NJ 08244 |
| [Historic Smithville](https://historicsmithvillenj.com/) | Family, theater, festivals, shopping | Reviewed public HTML/API | 615 E Moss Mill Road, Smithville, NJ 08205 |
| [Josie Kelly's Public House](https://josiekellys.com/events/) | Live music, social, food and drink | Reviewed public HTML/API | 908 Shore Road, Somers Point, NJ 08244 |
| [Noyes Museum of Art / Noyes Arts Garage](https://noyesmuseum.org/all-noyes-events) | Arts, workshops, exhibits, makers | Reviewed public HTML/API with durable continuation | Event-specific Arts Garage, Kramer Hall and other publisher venues |
| [Seaside Wellness Atlantic City](https://seasidewellnessac.com/events.html) | Fitness, yoga, wellness | Reviewed public HTML/API | The Pool at Harrah’s, 777 Harrah’s Boulevard, Atlantic City, NJ 08401 |
| [Somers Point Brewing Company](https://somerspointbrewing.com/) | Trivia, live music, social | Reviewed public HTML/API | 705 W New York Avenue, Somers Point, NJ 08244 |
| [Visit Atlantic City](https://www.visitatlanticcity.com/events/) | Tourism, entertainment, festivals, nightlife, sports | Reviewed public HTML/API with durable continuation | Publisher structured event venue; reviewed named-venue repairs where necessary |

## Collection and publication requirements

- Reuse the guarded public transport, WordPress TEC and iCalendar normalizers, existing category workers, v2 preview recording, publication queue, image verification and address geocoder.
- Preserve complete normalized publisher descriptions. The exact new source cohort uses the existing 12,000-character capacity through staging and both publication paths. Blank descriptions and oversized narratives fail or are explicitly held; no clipped record is certified.
- Register only exact reviewed source key/feed/kind/adapter/timezone tuples. Known venue streets are resolved from official publisher information. Boardwalk is accepted as an actual numbered street. Coverage centers are source-selection metadata and never event coordinates.
- Visit Atlantic City uses its complete public sitemap and full detail pages. RSS has only excerpts and a short first page. Its anonymous display API returned 403 and was not bypassed.
- Noyes follows the actual public HTML event links, including forward navigation. Its RSS lacks reliable event clocks and addresses. Both long calendars use fenced durable checkpoints; incomplete scans never stage or publish a partial snapshot.
- Expand recurrence only from explicit dates, weekdays and publisher clock rules. Apply America/New_York daylight-saving rules and source exceptions. Closures, virtual/unspecified locations, missing descriptions and unresolved clocks remain explicit holds.
- Preserve shared automatic classification. Do not apply venue-wide Music/Markets/Social labels. Capture the narrative-extraction lesson without introducing a regional classifier.

## Discovery holds and remaining leads

A discovered venue is not automatically an active event feed. These leads remain documented with observed reasons. No prohibited endpoint, login wall or rate limit is bypassed.

| Lead | Evidence | Reason |
| --- | --- | --- |
| Margate City Public Library | [Official source](https://www.margatelibrary.org/events/rss/feeds?per_page=100) | Active EBSCO Stacks RSS returns 200, but many entries have blank descriptions; detail and robots requests returned 403. Requires permitted access to full descriptions. |
| Greater Atlantic City Chamber | [Official source](https://business.acchamber.com/events/search?rendermode=rss) | Active calendar and public RSS return 200; API and robots requests returned 403. Requires publisher access verification and complete structured location mapping. |
| Jewish Federation / Katz JCC | [Official source](https://jewishbytheshore.org/events/) | Active public calendar pages; Events Calendar API and robots requests returned 403. Full narrative hydration and exact event-specific venue mapping remain unverified. |
| Jewish Family Service of Atlantic & Cape May Counties | [Official source](https://www.jfsatlantic.org/events/category/volunteer/2026-11/) | Active November 18 volunteer food distributions have official detail evidence. Events Calendar listing/API returned 503; stable allowed collection remains unverified. |
| Great Day Atlantic City | [Official source](https://www.greatdayatlanticcity.com/events) | Active Webflow community calendar has full detail narratives. Dedicated detail/date/pagination ingestion is needed; several entries provide flyer-only schedules. |
| Stockton Performing Arts Center | [Official source](https://stockton.edu/pac/events-list.html) | Active 2026–2027 show list has full narratives. Multi-performance HTML ingestion must distinguish campus venues from Atlantic City locations. |
| Stockton public university events | [Official source](https://www.stockton.edu/events/events-listing.html) | Active events include public, invitation-only and student-only programs. Requires individual venue and public eligibility resolution. |
| Absecon Lighthouse | [Official source](https://abseconlighthouse.org/__static/jdj5jdewjglibdlvsvfqaurawvn6s3lr/2026-Calendar-of-Events.pdf) | Official 2026 PDF includes December 4 Luminary Light Festival, 5–7 p.m. Annual PDF needs a reviewed schedule parser. |
| Oceanside I Family Success Center | [Official source](https://oceanside1fsc.org/calendar%2Fevents) | Current November 2026 PDF calendar. Noyes covers explicit art programs; remaining monthly programs require PDF ingestion. |
| Oceanside II Family Success Center | [Official source](https://oceanside2fsc.org/) | Programs appear through Noyes and Jewish Family Service. The main website supplies venue information and an image-based calendar. |
| Atlantic City Aquarium | [Official source](https://www.acnj.gov/pages/acaquarium) | Active admissions, exhibits and private party rentals. No separate future dated public event feed verified; ordinary opening hours are not event occurrences. |
| Marine Mammal Stranding Center | [Official source](https://mmsc.org/) | Official website links fundraisers, but the October 10 Pup Strut has ended. No future dated event feed verified. |
| Tennessee Avenue Beer Hall | [Official source](https://tennesseeavenuebeerhall.com/events/fm3lJ0vsG124) | Old Squarespace season endpoints cannot determine individual weekly clocks. New venue event page supplies conflicting noon–9 pm Sunday hours but page+robots return 403. No seasonal occurrences published. Old HTML collector supports new individual dated events when added. |
| Resorts Bar One | [Official source](https://resortsac.com/nightlife/bar-one/) | Current November 2026 schedule visible in web search; direct page and robots return 403. |
| Hard Rock Lobby Bar | [Official source](https://casino.hardrock.com/atlantic-city/event-calendar/live-music-at-lobby-bar) | Current dated music schedule but direct page and robots return 403. |
| The Leadership Studio | [Official source](https://www.leadershipstudioac.com/yoga-classes) | Official page embeds Momence host 29984; Momence plugin and robots return 403. Search-rendered clocks appear UTC; require explicit timezone-aware feed before ingestion. |
| Garden State Beer Company | [Official source](https://gardenstatebeerco.com/whats-happening%3F) | Official event page currently only October 2026 cards, no future dated November event schedule. Avoid projecting stale foodtruck/bookclub/trivia cards. |
| Little Water Distillery | [Official source](https://www.lwdco.com/) | Official page offers general tasting hours but special events redirect readers to social pages; no verified future datedpublic calendar. |
| The Seed: A Living Beer Project | [Official source](https://theseedbeer.com/) | Venue identified807 Baltic Avenue; no verified future datedofficial calendar found in this pass. |
| Ventnor Farmers Market | [Official source](https://www.vcfm.org/) | Published 2026 season ended September 4; do not fabricate 2027 dates. |
| Level Up Entertainment | [Official source](https://levelupentertainment.com/about) | Official store archive says retail store closed January 26, 2025; do not ingest archived gaming events. |
| NJ Audubon at Forsythe NWR | [Official source](https://njaudubon.org/venue/edwin-b-forsythe-national-wildlife-refuge/) | Official upcoming November 28 bird walk and street 800 Great Creek Road; directTECAPIandrobots return 403. |
| South Jersey Run Club | [Official source](https://runsignup.com/Race/NJ/AtlanticCity/SouthJerseyRunClub) | Discovery returns expired June 2026 instances. Do not project wording every Saturday beyond confirmed dated schedule. |
| Historic Smithville Girls Night Out / Breakfast with Santa | [Official source](https://historicsmithvillenj.com/?page=2) | Current calendar dates exist but no start clock supplied; breakfast venue Fred & Ethel’s has distinct address. Dickens and Hospitality successfully implemented. |
| Funny Farm Rescue winter hayride and market | [Official source](https://funnyfarmrescue.org/) | Official homepage advertises December 6, 2026, noon–3 PM at 6908 Railroad Blvd, Mays Landing, NJ 08330. Direct homepage and robots requests return HTTP 403; no bypass attempted. |

## Verification and release

Publisher snapshots and focused parser/worker tests verify full prose, exact dates, recurrence exceptions, street addresses, source identity, checkpoint durability and complete-only publication. The scratch runtime cannot resolve publisher DNS through the guarded transport; public research fetches are parsing evidence, not production transport success. Production verification must read the actual collector receipts, staged rows and public events after deployment.

Deploy the consolidated collector batch first. Once that production deployment is READY, merge the application migration and manually dispatch the existing Database deploy workflow from current main. That workflow retains history/order, exact dry-run, push and readback safeguards. Do not start routine CI, provider test workflows or one workflow per source. Release evidence records actual deployment and ingestion results separately from parser evidence.

### Classifier transfer observation

The four pre-labeled synthetic transfer cases kept the correct primary category in all four, and matched the complete category list in three. The sewing example retained Create but did not add the expected secondary Learn category. This is recorded as an existing shared-classifier follow-up; no regional override or relabeled passing expectation was introduced. These four examples are not a population accuracy measure.
