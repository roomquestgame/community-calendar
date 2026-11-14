# Atlantic City independent-source batch — November 14, 2026

## Implementation and captured proof at merge

This document records the implementation and captured verification prepared for the consolidated merge. **Production deployment, guarded collection and staged/public verification were pending when this record was prepared.** The [canonical production report](https://github.com/roomquestgame/RoomQuestGame/blob/main/docs/evidence/atlantic-city-independent-production-report.md) maintains the current release status, deployment receipts and runtime verification as that work proceeds.

The batch adds **nine new sources** for independent dining and nightlife, markets, public recreation and trading-card events. The reviewed manifest is `research-ac/independent-source-manifest.json`, batch `atlantic-city-independent-20261114`; its predeployment `production_verified` value was **false**. The captured expectation is **380 eligible occurrences**, including 23 from Reed's Farm. Successful deployment and actual collection/publication proof must be recorded in the canonical report before these sources are described as live.

The production baseline observed at **2026-11-14 21:52:28.672087 UTC** was **26 working sources and 850 active public occurrences**. Those working sources remain the baseline and are not newly enrolled by this batch. **Visit Atlantic City is owner-disabled** and excluded from working coverage. Earlier paused/HTTP-403 wording in historical batch documents records its previous status.

All nine profiles use `kind=html`, `platform_adapter=html` and `America/New_York`, with exact source-key/feed/adapter/timezone validation. Their 30-mile discovery circles select local sources; they are never event map points. The current bounded snapshots fit the normal guarded collection path and do not require checkpoints.

## Nine-source manifest and captured expectation

| Publisher and source key | Captured eligible occurrences | Complete description and schedule path | Reviewed street address |
| --- | ---: | --- | --- |
| [Clancy's By The Bay](https://clancysrestaurantgroup.com/calendar/clancys-by-the-bay/) — `clancys_by_the_bay_nj` | 4 | Official Simple Calendar HTML contains complete karaoke/trivia prose and individual dated occurrences. Native identity, ISO offset, Unix timestamp and visible clock must agree. | 101 E Maryland Ave, Somers Point, NJ 08244 |
| [Cardinal Atlantic City](https://www.cardinal-ac.com/events-at-cardinal) — `cardinal_atlantic_city_nj` | 4 | Public Squarespace calendar plus complete event detail bodies for wine tastings, supper-club dining and social programs. | 201 S New York Avenue, Atlantic City, NJ 08401 |
| [Renault Winery & Resort](https://renaultwinery.com/events/list/) — `renault_winery_nj` | 23 | Native public Tribe Events API descriptions and explicit individual occurrences, including tastings, classes, music and family programs. | 72 North Bremen Avenue, Egg Harbor City, NJ 08215 |
| [Atlantic City Country Club public events](https://accountryclub.com/events/list/) — `atlantic_city_country_club_nj` | 2 | Native public Tribe Events API descriptions for public dining and family events; private activity and taproom closures are excluded. | 1 Leo Fraser Drive, Northfield, NJ 08225 |
| [Ventnor Social](https://ventnorsocial.com/events) — `ventnor_social_nj` | 1 | Current Holiday Market paragraph is the complete publisher text: the detail body is explicitly empty and all description metadata agrees with that exact reviewed paragraph. | 6417 Ventnor Avenue, Ventnor City, NJ 08406 |
| [Egg Harbor Township Recreation](https://eggharbornj.myrec.com/info/calendar/list.aspx?FacilityID=14784&AreaID=0) — `egg_harbor_township_recreation_nj` | 30 | Individual dated facility sessions joined to complete Adult Open Gym or Mindful Chair and Standing Yoga program prose, relevant sport notes, instructor and participation conditions. | 5045 English Creek Avenue, Egg Harbor Township, NJ 08234 |
| [Ocean City Aquatic & Fitness Center](https://www.ocnj.us/departments/CommunityServices/Aquatic-and-Fitness-Center) — `ocean_city_aquatic_fitness_nj` | 292 | Reviewed winter PDF grid and complete native class definitions, supplemented by the entire Water Exercise FAQ and intact current HTML reservation policy. | 1735 Simpson Avenue, Ocean City, NJ 08226 |
| [Atlantic City TCG Show](https://atlanticcitytcgshow.com/) — `atlantic_city_tcg_show_nj` | 1 | Explicit December 20, 2026 show date, both admission phases, family admission conditions and all five native About sections. The phases form one show. | Showboat Resort Atlantic City, 801 Boardwalk, Atlantic City, NJ 08401 |
| [Reed's Farm](https://www.reedsorganicfarm.org/events) — `reeds_farm_nj` | 23 | Full native public Boom Calendar descriptions, individually dated workshops and vendor events, and the publisher-defined finite Pizza Day recurrence. | 5075 Spruce Ave, Egg Harbor Township, NJ 08234 |
| **Total captured expectation** | **380** | **Captured implementation evidence at merge** | |

The counts are timestamped parser expectations. Publication must account for actual publisher changes, occurrences expiring during release, canonical duplicates and explicit holds. The release proof must report those outcomes rather than equating a successful deployment with 380 newly public events.

## Full-description safeguards

Collectors retain the **complete normalized publisher narrative**. This means the complete text of the applicable event body or class definition after markup normalization; it does not promise literal HTML preservation. Relevant admission phases, equipment rules, age restrictions, waiver instructions, public eligibility and cancellation instructions are retained where the publisher supplies them. Already-normalized text is validated without another HTML parse, preserving escaped literal instructions such as angle-bracket text.

Blank descriptions are rejected or held explicitly. Narratives longer than **12,000 characters** are rejected, never sliced. Source snapshots exceeding **500 accepted occurrences** fail rather than returning a clipped subset. The exact nine-source cohort uses the complete-description staging/publication contract; final verification must compare the collector's normalized text with both staged and public records through the relevant publication paths.

The four independent dining/venue sources have 30 captured records with complete-description equality and full street/ZIP addresses. Their longest narrative is 2,773 characters. The two recreation sources have 322 captured records with zero blank descriptions; the longest EHT and Ocean City bodies are 1,529 and 647 characters respectively. The TCG Show body is 652 characters. Reed's current 23-record replay has zero blank descriptions and a maximum length of 1,885 characters.

Ventnor Social has a narrow, event-specific exception for its complete 234-character Holiday Market paragraph. The parser verifies the empty detail body and matching native metadata; it does not generally substitute listing excerpts for event descriptions. A changed or unreviewed excerpt fails. Ocean City's PDF registration box is visually clipped by the publisher; its intact current HTML reservation paragraph supplies those instructions, while all accepted class definitions are complete.

Existing anonymous-display and SEO disclosure rules remain applicable. The complete-storage contract and staged/public hash checks establish ingestion integrity; they do not override those display rules.

## Dates, recurrence and eligibility

Clancy's and EHT use individual dates present in the publisher's current calendar. Clancy's current-month schedule is not projected into later months. EHT's next-month facility list is not expanded from its broader seasonal registration ranges; duplicate court/room allocations are consolidated by native activity and occurrence. A listed session must agree with the program's weekday, date range and clocks. Seasonal registration being unavailable does not negate the two programs' explicit public drop-in option; native space, waiver, equipment and punch-card conditions remain intact.

Renault and Atlantic City Country Club have a narrowly reviewed publisher configuration that labels New Jersey wall clocks as UTC+0. Only these exact feeds interpret those values in `America/New_York`, corroborated against their visible publisher schedules. The Renault music item showing a 15-hour set remains held; no AM/PM correction is guessed. Unknown ends remain unknown.

Ocean City's winter schedule explicitly runs **November 9, 2026–March 7, 2027**. The visually reviewed weekday-to-cell mapping is bound to the exact current PDF SHA-256 and live publisher link. The collector accepts 46 of 70 weekly cells with complete native definitions. The other 24 cells represent 13 undefined class variants and remain held. The linked cycling flyer is internally Spring 2026 despite a misleading 2027 link label and cannot supply current cycling prose.

Ocean City's current holiday document covers **2026**, so the reviewed occurrence horizon stops on **December 31, 2026**. Thanksgiving Day and Christmas Day are excluded. Christmas Eve and New Year's Eve apply the published **1 p.m. closing time**. January exceptions are not inferred from the prior year's document. Changed PDFs or removed current links require review and fail explicitly; expired holiday scope also fails. Only explicit one-hour land-class markers and the publisher's 45-minute Water Exercise schedule supply end times.

Reed's ordinary anonymous visitor configuration identifies the public Boom calendar. The collector binds the website, app, component, public guest instance, calendar ID, timezone and native event identities; it sends the unchanged server-issued public instance only to the reviewed published-calendar endpoint. It requires no account login or extra credential headers. Complete event narratives and actual event venue data come from that calendar. Finite weekly recurrence and exclusion counting follow the publisher widget's verified rules. Published closures, preorder-only retail notices and missing-description records remain excluded. In particular, November 15's Heritage Surf entry has no description and does not inherit the previous day's body.

Private, cancelled, sold-out or unresolved programs remain subject to each collector's native eligibility checks. Outdated 2025 Ventnor trivia and Santa items are not projected into 2026. TCG tournament details marked TBD remain part of the show narrative and do not create a separately timed tournament.

## Address and map-location provenance

Every accepted capture has a full numbered street, locality, state and ZIP. Venue resolution uses the actual publisher venue and reviewed address evidence. Known map points are bound to exact source/venue/street identities so a changed address cannot inherit another venue's point. Coverage-circle coordinates never enter event records.

Clancy's, Cardinal, Renault, Ventnor Social, EHT Community Center and Showboat use reviewed New Jersey Office of GIS address points. Renault's official contact page corroborates **72 Bremen Avenue** for the same resort as the event API's **72 North Bremen Avenue**; event records retain the publisher's North variant. The estate point does not claim a particular room. Reed's uses the native event venue coordinates associated with the farm street.

Two map destinations visibly state **“approximate map location”**:

- **Atlantic City Country Club:** the full publisher street is **1 Leo Fraser Drive, Northfield, NJ 08225**. The point **39.37029755, -74.54236135** is the reviewed clubhouse polygon centroid, matched to the official club name, website and phone. It is not a surveyed entrance or dining-room position. Geometry: [OpenStreetMap way 630332016](https://www.openstreetmap.org/api/0.6/way/630332016/full), © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), ODbL.
- **Ocean City Aquatic & Fitness Center:** the full publisher street is **1735 Simpson Avenue, Ocean City, NJ 08226**. NJ OGIS returned a score-100 `StreetAddress` interpolation at **39.271761871741, -74.59048756658**, rather than a `PointAddress`. The street remains exact and the map destination is explicitly approximate.

See the [independent venue audit](../../docs/evidence/atlantic-city-independent-venues-20261114.json), [venue point evidence](../../docs/evidence/atlantic-city-independent-venue-points.json), [recreation audit](../../docs/evidence/atlantic-city-recreation-2026-11-14.json), and [markets/gaming audit](../../docs/evidence/atlantic-city-markets-gaming-20261114.json).

## Holds outside the nine-source batch

| Source | Current outcome | Effect on this batch |
| --- | --- | --- |
| [Top Deck Games — EHT](https://www.topdeckgamesonline.com/) | Research-only parser/captures exist, but Google robots disallows the public iCalendar feed path. The source is absent from active collector profiles, and collection rejects its key before I/O. | No enrollment or publication; its captured records are excluded from the 380 expectation. No alternate prohibited route is used. |
| [Seven Tap Tavern / Blue Heron Pines](https://blueheronpines.com/upcoming-events/) | The individual [DJ Trivia](https://blueheronpines.com/events/dj-trivia/) and [live music](https://blueheronpines.com/events/live-music-with-roger-tom-3/) details returned HTTP 403. Full descriptions cannot be verified from those blocked details. | Held; listing snippets are not promoted into certified complete descriptions and the 403 is not bypassed. |
| [Visit Atlantic City](https://www.visitatlanticcity.com/events/) | Explicitly disabled by the owner after its earlier production HTTP-403 hold. | Remains disabled; no retry, reenrollment or captured-tourism coverage claim. |

Existing working sources and historical source records are preserved. Other discovery leads remain documented separately, including expired schedules and sources with unresolved public calendars; they are not silently enrolled by this batch.

## Validation and release proof

The combined local verification run passed **96 tests** across the four new adapter modules, all nine category/preview routes and the existing Atlantic City worker regressions. These checks exercise full long narratives, escaped literal text, blank/over-limit rejection, native source identity, event clocks, recurrence exceptions, closures, public eligibility and exact street/point binding. The focused recreation suite contributes 16 tests and the independent venue suite contributes 18. Later verification receipts are maintained in the canonical production report.

The application repository contains the [380-occurrence captured hash audit](https://github.com/roomquestgame/RoomQuestGame/blob/main/docs/evidence/atlantic-city-independent-capture-20261114.json) and the [batch verification SQL](https://github.com/roomquestgame/RoomQuestGame/blob/main/docs/evidence/atlantic-city-independent-verification.sql). They define the expected identities, full descriptions, postal streets and readback checks. The [canonical production report](https://github.com/roomquestgame/RoomQuestGame/blob/main/docs/evidence/atlantic-city-independent-production-report.md) records observed results.

Ordinary public HTTP captures and parser replays succeeded. The scratch environment's guarded publisher transport returned `dns_unavailable`; its DNS, robots, pacing, host, byte and deadline controls were unchanged. These captures establish parser behavior. **Production transport and publication remained unverified at documentation freeze.**

Deploy the consolidated collector changes first. After the production collector is READY, apply the consolidated backend source/migration batch through the existing Database deploy workflow. Keep the work in multi-item PRs and a shared deployment run. The owner-disabled routine CI/test-workflow policy remains in force; a source does not receive its own PR or workflow run.

The release owner maintains the following receipts in the canonical production report. This table records the proof that was still pending at the implementation merge, rather than serving as a second runtime status tracker:

| Proof item | Status at implementation documentation freeze |
| --- | --- |
| Collector PR and merged revision | Pending |
| Production collector deployment ID and READY state | Pending |
| Backend PR, merged revision and migration version | Pending |
| Consolidated Database deploy run and migration readback | Pending |
| Guarded production completion for all nine sources | Pending |
| Staged occurrence count, complete-description hashes and full street equality | Pending |
| Published occurrence count, complete-description hashes and full street equality | Pending |
| Canonical overlaps, publisher changes, expired events and explicit holds reconciled | Pending |
| Existing 26-source baseline preserved; Visit Atlantic City still disabled | Pending |
| Final active-public count and observation timestamp | Pending |

Successful parser verification or a READY deployment alone does not establish completed publication. The canonical final proof must reconcile the captured expectation with actual staged and public outcomes and identify any remaining collection, address or publication failures.
