# Atlantic City source discovery and implementation — November 14, 2026

## Scope and production baseline

Ben authorized broad local discovery, full-description ingestion, street-address resolution, batched PRs and production deployment, including Visit Atlantic City. Before this work, production inspection found no registered Atlantic City-area community sources; the initial 15-mile future-event sample contained 126 Ticketmaster events. Existing working sources are outside this change. Nearby county calendars are included, while event coordinates identify reviewed venue or campus destinations rather than coverage centers.

The [recorded verification of the first batch](../../docs/evidence/atlantic-city-remaining-source-audit-20261114.json) found **585 active public events across 11 collected sources**, with no staged/public description mismatches or incomplete postal addresses. Its twelfth source, **Visit Atlantic City, remains paused after production returned `publisher_http_403`**. Captured tourism results are not working production coverage. All seven additional implementations have completed production collection with **43 staged occurrences** whose full description hashes and postal streets match the checked publisher responses. At the first completed readback, **40 additional occurrences were public**; Ducktown Tree Lighting correctly matched the existing Noyes occurrence, while Carnegie Center and Pop Lloyd Stadium required the reviewed map points supplied in the final correction batch. The combined cohort had **625 active public events**, all with complete descriptions and postal streets. Final publication receipts are recorded in the application repository’s Atlantic City production report.

## Initial 12-source batch

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
| [Visit Atlantic City](https://www.visitatlanticcity.com/events/) | Tourism, entertainment, festivals, nightlife, sports | Implemented with durable continuation; production paused after HTTP 403 | Publisher structured event venue; reviewed named-venue repairs where necessary |

## Seven additional implemented sources — production collected

| Publisher | Captured eligible occurrences | Collection path | Address resolution |
| --- | ---: | --- | --- |
| [Great Day Atlantic City](https://www.greatdayatlanticcity.com/events) | 13 | Complete Webflow detail bodies, actual upcoming pagination and durable complete-only checkpoints | Event-specific numbered streets; conflicting school location and unresolved parade route remain held |
| [Stockton Performing Arts Center](https://stockton.edu/pac/events-list.html) | 16 | Complete public performance cards plus bounded native 25Live iCalendar narratives; separate dated performances | 101 Vera King Farris Drive, Galloway, NJ 08205; actual named rooms where verified, campus-level venue for Charlie Brown |
| [Stockton Holocaust Resource Center](https://stockton.edu/holocaust-resource/events/index.html) | 1 | Complete dated public lecture body and subtitle | L-112 Lecture Hall, 101 Vera King Farris Drive, Galloway, NJ 08205 |
| [Stockton Center on Successful Aging](https://www.stockton.edu/aging/events-workshops.html) | 1 | Complete public workshop card; PAC duplicates excluded and no projected monthly recurrence | Stockton Atlantic City campus, 3711 Atlantic Avenue, Atlantic City, NJ 08401 |
| [Absecon Lighthouse](https://abseconlighthouse.org/__static/jdj5jdewjglibdlvsvfqaurawvn6s3lr/2026-Calendar-of-Events.pdf) | 1 | Entire remaining dated program paragraph from the official annual PDF | 31 South Rhode Island Avenue, Atlantic City, NJ 08401 |
| [Oceanside I Family Success Center](https://oceanside1fsc.org/calendar%2Fevents) | 6 | Current publisher-linked November PDF; complete native prose and reviewed calendar-cell dates | 201 Melrose Avenue Unit 3, Atlantic City, NJ 08401; one explicitly labeled college-campus estimate for Friendsgiving |
| [Oceanside II Family Success Center](https://oceanside2fsc.org/calendar) | 5 | Current English November PDF; complete native prose and reviewed calendar-cell dates | 3201 Atlantic Avenue, Atlantic City, NJ 08401 |
| **Total captured expectation** | **43** | | |

Collector [PR #211](https://github.com/roomquestgame/community-calendar/pull/211) and backend [PR #912](https://github.com/roomquestgame/RoomQuestGame/pull/912) are merged. Collector deployment `dpl_FZsWpzt3B23NLf2QsPW5uWzVBKvo` is READY. [Database deploy 43637780151](https://github.com/roomquestgame/RoomQuestGame/actions/runs/43637780151) succeeded, applied the seven-source migration and verified all 476 repository migration versions on production. Actual production readback found no blank, over-limit or truncated descriptions and no incomplete postal streets in the collected/published cohort. See [the remaining-source batch](REMAINING_SOURCE_BATCH.md) and [its machine-readable captured audit](../../docs/evidence/atlantic-city-remaining-source-audit-20261114.json).

## Collection and publication requirements

- Reuse the guarded public transport, WordPress TEC and iCalendar normalizers, existing category workers, v2 preview recording, publication queue, image verification and address geocoder.
- Preserve complete normalized publisher descriptions. The exact new source cohort uses the existing 12,000-character capacity through staging and both publication paths. Blank descriptions and oversized narratives fail or are explicitly held; no clipped record is certified.
- Register only exact reviewed source key/feed/kind/adapter/timezone tuples. Known venue streets are resolved from official publisher information. Boardwalk is accepted as an actual numbered street. Coverage centers are source-selection metadata and never event coordinates.
- Visit Atlantic City uses its complete public sitemap and full detail pages. RSS has only excerpts and a short first page. Its anonymous display API returned 403 and was not bypassed.
- Noyes follows the actual public HTML event links, including forward navigation. Its RSS lacks reliable event clocks and addresses. Noyes, Visit Atlantic City and the municipal detail calendar use fenced durable checkpoints; incomplete scans never stage or publish a partial snapshot.
- Great Day also uses durable complete-only checkpoints. It excludes three exact occurrences already owned by the primary municipal/library sources; overlaps with Visit Atlantic City remain eligible because Visit is not publishing.
- Stockton retains complete public card and native calendar narratives, including public homeschool eligibility. Its public performance schedule controls occurrence clocks; conflicting native times do not overwrite it. The collector does not fetch the robots-disallowed ticket host. HRC retains its actual L-112 room without borrowing the theatre's coordinates; Charlie Brown uses the verified Galloway campus street and campus-level map destination without claiming a room.
- Oceanside I and II re-download their publisher-linked PDFs and retain the complete native prose. Reviewed calendar-cell mappings are bound to the exact November PDF SHA-256. **A changed monthly PDF requires review and fails explicitly**; November programs are not projected into another edition or month.
- Oceanside I's November 19 Friendsgiving uses **1535 Bacharach Boulevard, Atlantic City, NJ 08401-4485**, with the visible venue qualifier **“Atlantic City campus (address estimated)”**. The current PDF names Atlantic Cape Community College without a campus. Prior Oceanside dinner evidence and the college's current directory support this contextual estimate; the current publisher has not confirmed the 2026 campus, and no publisher GPS point is invented.
- Expand recurrence only from explicit dates, weekdays and publisher clock rules. Apply America/New_York daylight-saving rules and source exceptions. Closures, virtual/unspecified locations, missing descriptions and unresolved clocks remain explicit holds.
- Preserve shared automatic classification. Do not apply venue-wide Music/Markets/Social labels. Capture the narrative-extraction lesson without introducing a regional classifier.

## Discovery holds and remaining leads

A discovered venue is not automatically an active event feed. These leads remain documented with observed reasons. No prohibited endpoint, login wall or rate limit is bypassed.

| Lead | Evidence | Reason |
| --- | --- | --- |
| Margate City Public Library | [Official source](https://www.margatelibrary.org/events/rss/feeds?per_page=100) | Active EBSCO Stacks RSS returns 200, but many entries have blank descriptions; detail and robots requests returned 403. Requires permitted access to full descriptions. |
| Greater Atlantic City Chamber | [Official source](https://business.acchamber.com/events/search?rendermode=rss) | Active calendar and public RSS return 200; API and robots requests returned 403. Requires publisher access verification and complete structured location mapping. |
| Jewish Federation / Katz JCC | [Official source](https://jewishbytheshore.org/events/) | Active public calendar pages; Events Calendar API and robots requests returned 403. Full narrative hydration and exact event-specific venue mapping remain unverified. |
| Jewish Family Service of Atlantic & Cape May Counties | [Fresh November month page](https://www.jfsatlantic.org/events/month/2026-11/?shortcode=f0b1cb7d) | Fresh November page returns HTTP 200 but contains no Oceanside distribution; the previously indexed November 18 detail now returns HTTP 404. No current independent JFS occurrence is verified. The current Oceanside II PDF supplies the November 18 distribution at noon–1 p.m.; stale indexed 1–2 p.m. text is not retained as a timing conflict. |
| Other records in Stockton's university-wide calendar | [Official source](https://stockton.edu/calendars/index.html) | PAC, HRC and SCOSA public programs are implemented above. The wider calendar also contains private, invitation-only and student-only scheduling, and its default export caps at 200 rows. Unreviewed or nonpublic records are excluded; bounded PAC records are matched to the public performance manifest. |
| Atlantic City Aquarium | [Official source](https://www.acnj.gov/pages/acaquarium) | Active admissions, exhibits and private party rentals. No separate future dated public event feed verified; ordinary opening hours are not event occurrences. |
| Marine Mammal Stranding Center | [Official source](https://mmsc.org/) | Official website links fundraisers, but the October 10 Pup Strut has ended. No future dated event feed verified. |
| Tennessee Avenue Beer Hall | [Official source](https://tennesseeavenuebeerhall.com/events/fm3lJ0vsG124) | Old Squarespace season endpoints cannot determine individual weekly clocks. New venue event page supplies conflicting noon–9 pm Sunday hours but page+robots return 403. No seasonal occurrences published. Old HTML collector supports new individual dated events when added. |
| Resorts Bar One | [Official source](https://resortsac.com/nightlife/bar-one/) | Current November 2026 schedule visible in web search; direct page and robots return 403. |
| Hard Rock Lobby Bar | [Official source](https://casino.hardrock.com/atlantic-city/event-calendar/live-music-at-lobby-bar) | Current dated music schedule but direct page and robots return 403. |
| The Leadership Studio | [Official source](https://www.leadershipstudioac.com/yoga-classes) | Official page embeds Momence host 29984; Momence plugin and robots return 403. Search-rendered clocks appear UTC; require explicit timezone-aware feed before ingestion. |
| Garden State Beer Company | [Official source](https://gardenstatebeerco.com/whats-happening%3F) | Official event page currently only October 2026 cards, no future dated November event schedule. Avoid projecting stale foodtruck/bookclub/trivia cards. |
| Little Water Distillery | [Official source](https://www.lwdco.com/) | Official page offers general tasting hours but special events redirect readers to social pages; no verified future dated public calendar. |
| The Seed: A Living Beer Project | [Official source](https://theseedbeer.com/) | Venue identified at 807 Baltic Avenue; no verified future dated official calendar found in this pass. |
| Ventnor Farmers Market | [Official source](https://www.vcfm.org/) | Published 2026 season ended September 4; do not fabricate 2027 dates. |
| Level Up Entertainment | [Official source](https://levelupentertainment.com/about) | Official store archive says retail store closed January 26, 2025; do not ingest archived gaming events. |
| NJ Audubon at Forsythe NWR | [Official source](https://njaudubon.org/venue/edwin-b-forsythe-national-wildlife-refuge/) | Official upcoming November 28 bird walk and street 800 Great Creek Road; direct TEC API and robots return 403. |
| South Jersey Run Club | [Official source](https://runsignup.com/Race/NJ/AtlanticCity/SouthJerseyRunClub) | Discovery returns expired June 2026 instances. Do not project wording every Saturday beyond confirmed dated schedule. |
| Historic Smithville Girls Night Out / Breakfast with Santa | [Official source](https://historicsmithvillenj.com/?page=2) | Current calendar dates exist but no start clock supplied; breakfast venue Fred & Ethel’s has distinct address. Dickens and Hospitality successfully implemented. |
| Funny Farm Rescue winter hayride and market | [Official source](https://funnyfarmrescue.org/) | Official homepage advertises December 6, 2026, noon–3 PM at 6908 Railroad Blvd, Mays Landing, NJ 08330. Direct homepage and robots requests return HTTP 403; no bypass attempted. |

### Event-level holds within implemented calendars

- Great Day's North Meets South Party lacks a reliable published clock. Its holiday parade lacks a resolved route-start street. The November 19 South Jersey Gas event pairs New York Avenue School with a street belonging to Pennsylvania Avenue School; no current relocation evidence resolves the conflict.
- Stockton's *A More Perfect Union* native notes explicitly state that registration is sold out. The eligible homeschool Nutcracker retains its complete published audience restrictions. The public *Manifest: Thirteen Colonies* lecture remains owned by the Noyes source, avoiding a duplicate university registration.
- The initial municipal source's Third Ward Document Shredding occurrence remains unpublished because the publisher supplies only a numbered block. Its documented block-level street estimate is not represented as a verified building or event GPS point.

## Verification and release

Publisher snapshots and focused parser/worker tests verify full prose, exact dates, recurrence exceptions, street addresses, source identity, checkpoint durability and complete-only publication. The scratch runtime cannot resolve publisher DNS through the guarded transport; public research fetches are parsing evidence, not production transport success. Production verification must read the actual collector receipts, staged rows and public events after deployment.

Deploy the consolidated collector batch first. Once that production deployment is READY, merge the application migration and manually dispatch the existing Database deploy workflow from current main. That workflow retains history/order, exact dry-run, push and readback safeguards. Do not start routine CI, provider test workflows or one workflow per source. Release evidence records actual deployment and ingestion results separately from parser evidence.

### Classifier transfer observation

The four pre-labeled synthetic transfer cases kept the correct primary category in all four, and matched the complete category list in three. The sewing example retained Create but did not add the expected secondary Learn category. This is recorded as an existing shared-classifier follow-up; no regional override or relabeled passing expectation was introduced. These four examples are not a population accuracy measure.
