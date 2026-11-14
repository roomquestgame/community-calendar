# New York City final source inventory and remaining delta — 14 November 2026

The three consolidated batches cover **62 task source profiles: 48 new registrations and 14 repairs of pre-existing sources with no active public events in the baseline**. Batch 3 closes the feasible arts/library, family, gaming, fitness, university and citywide Parks work identified after the first two releases. This file supersedes the *remaining-work* sections of the [frozen first/second-batch inventory](REMAINING_SOURCES_20261114.md); that earlier evidence remains unchanged.

This is a source and capture inventory. **Captured occurrences are not production publication counts.** The release owner appends the actual production deployment and readback receipt at the end. A source may be implemented yet still held by a real publisher access failure; Greenlight is explicitly identified below.

| Consolidated batch | Profiles | New | Existing zero-public repairs | Captured eligible source occurrences |
| --- | ---: | ---: | ---: | ---: |
| B1 | 28 | 23 | 5 | 790 |
| B2 | 11 | 3 | 8 | 615 |
| B3 | 23 | 22 | 1 | 902 |
| Task total | 62 | 48 | 14 | 2307 |

Each capture is immutable and has its own observation time/window. Expiration, deduplication, ownership and explicit rejected records mean that adding capture counts cannot establish a current unique public-event total. B3 comprises 73 arts/library, 72 social/gaming, 723 outdoors/civic/fitness and 34 zoo/aquarium occurrences.

Already-working baseline sources, including Scandinavia House, Food Bank for New York City and Brooklyn Bird Club, were excluded from enrollment changes. Follow-up location corrections target only specific still-unpublished rows and do not reenroll a fully working source cohort. Every repair retains the existing source key and guarded numeric registry identity.

## Source inventory

Every task profile appears once, under a primary category from the requested discovery framework; many calendars span several categories. `B1`, `B2` and `B3` refer to consolidated source releases, not one-source PRs or workflow runs. Address examples are actual venue streets; multi-location profiles retain their individual reviewed locations.

### Nightlife & Social

| Official source / calendar | Source key | Batch / action | Captured | Collector and physical-location decision |
| --- | --- | --- | ---: | --- |
| [Chilo’s](https://www.chilosbk.com/eventscalendar) — Brooklyn | `chilos_brooklyn_ny` | B1 / new | 5 | Squarespace HTML; 323 Franklin Avenue, Brooklyn, NY 11238. |
| [Forever Brewing](https://www.foreverbrewing.com/events-calendar) — Brooklyn | `forever_brewing_brooklyn_ny` | B1 / new | 19 | Squarespace HTML; 574 President Street, Brooklyn, NY 11215. Native calendar clocks checked against visible local times. |
| [Fifth Hammer Brewing](https://www.fifthhammerbrewing.com/fifth-hammer-calendar) — Queens | `fifth_hammer_queens_ny` | B1 / new | 18 | Permitted current-month Squarespace HTML; 10-28 46th Avenue, Long Island City, NY 11101. |
| [Starr Bar](https://www.starrbar.com/events) — Brooklyn | `starr_bar_brooklyn_ny` | B1 / new | 8 | Complete native Squarespace bodies; 214 Starr Street, Brooklyn, NY 11237. |
| [Skinny Dennis](https://skinnydennisbrooklyn.com/calendar) — Brooklyn | `skinny_dennis_brooklyn_ny` | B1 / new | 21 | Squarespace HTML; 152 Metropolitan Avenue, Brooklyn, NY 11249. |
| [Kills Boro Brewing Co.](https://killsboro.com/events) — Staten Island | `kills_boro_staten_island_ny` | B1 / new | 18 | HTML event JSON-LD matched to complete visible paragraphs; 814 Richmond Terrace, Staten Island, NY 10301. |
| [Wild East Brewing Co.](https://www.wildeastbrewing.com/) — Brooklyn | `wild_east_brooklyn_ny` | B3 / new | 4 | Current dated November program lines in permitted Squarespace HTML; 623 Sackett Street, Brooklyn, NY 11217. |
| [Bronx Alehouse — Let’s Go Trivia](https://letsgotrivia.com/venue/bronx-alehouse/) — Bronx | `bronx_alehouse_bronx_ny` | B3 / new | 9 | Official trivia organizer’s TEC venue feed with complete native body; 216 West 238th Street, Bronx, NY 10463. Publisher narrative repairs the malformed structured ZIP. |
| [Radegast Hall](https://radegasthall.com/) — Brooklyn | `radegast_hall_brooklyn_ny` | B3 / new | 12 | Public Amelia widget API, both pages and full native descriptions; 113 North 3rd Street or licensed alternate premises 186 Berry Street, Brooklyn, NY 11249. Durable one-request checkpoints respect the 60-second delay. |

### Arts, Culture & Education

| Official source / calendar | Source key | Batch / action | Captured | Collector and physical-location decision |
| --- | --- | --- | ---: | --- |
| [Staten Island Museum](https://www.statenislandmuseum.org/events/) — Staten Island | `staten_island_museum_ny` | B1 / new | 6 | TEC REST; museum and park-specific venues remain separate. Museum: 1000 Richmond Terrace Building A, Staten Island, NY 10301. |
| [Museum of the Moving Image](https://movingimage.org/events/) — Queens | `museum_of_moving_image_ny` | B1 / new | 92 | TEC REST; reviewed onsite categories map to 36-01 35th Avenue, Astoria, NY 11106. Later exact PAD point correction has separate evidence. |
| [Poster House](https://posterhouse.org/events/) — Manhattan | `poster_house_ny` | B1 / new | 13 | TEC REST; in-person/hybrid public events at 119 West 23rd Street, New York, NY 10011. |
| [Lewis Latimer House](https://www.lewislatimerhouse.org/events) — Queens | `lewis_latimer_house_ny` | B1 / new | 3 | Permitted Squarespace full details; 34-41 137th Street, Flushing, NY 11354. Unresolved offsite venue held. |
| [Historic Richmond Town](https://www.historicrichmondtown.org/events) — Staten Island | `historic_richmond_town_ny` | B1 / new | 3 | Permitted Squarespace full details; 441 Clarke Avenue, Staten Island, NY 10306. Multi-day season blurbs do not create invented occurrences. |
| [NYU — Open to the Public](https://events.nyu.edu/) — Manhattan / Brooklyn | `municipal_mapsee_59cd82df6a4f146d4b15acec` | B2 / repair 3550 | 36 | Documented LiveWhale JSON with requested full description and exact native venue IDs/points; accepted snapshot has eight distinct streets. |
| [The Bronx Museum](https://bronxmuseum.org/events/) — Bronx | `bronx_museum_ny` | B2 / new | 3 | Public HTML cards and full details; 1040 Grand Concourse, Bronx, NY 10456. |
| [New York Transit Museum](https://www.nytransitmuseum.org/programs/) — Brooklyn / Manhattan | `ny_transit_museum_ny` | B3 / new | 17 | Native TEC schedule plus full public detail bodies repair all blank API descriptions. Museum 99 Schermerhorn Street, Brooklyn, NY 11201; separate station boarding/meeting locations retain full instructions and visible approximations where applicable. |
| [Flushing Town Hall](https://www.flushingtownhall.org/events) — Queens | `flushing_town_hall_ny` | B3 / new | 12 | Full custom calendar details and native performance date/time tables; 137-35 Northern Boulevard, Flushing, NY 11354, plus six independently reviewed offsite venues. |
| [Brooklyn Public Library — BPL Presents](https://www.bklynlibrary.org/bpl-presents/events) — Brooklyn | `brooklyn_public_library_presents_ny` | B3 / new | 12 | Explicit BPL Presents series, complete Drupal main-column biographies/body rather than the truncated calendar-export description; four actual branches with numbered streets and exact PAD points. |
| [Fordham University](https://calendar.fordham.edu/) — Bronx / Manhattan | `fordham_university_ny` | B3 / new | 15 | All native Localist pages, full descriptions and public NYC scope; actual campus buildings and offsite venues. Rose Hill building access estimates are visibly approximate; the old calendar is not enrolled again. |

### Outdoor & Active

| Official source / calendar | Source key | Batch / action | Captured | Collector and physical-location decision |
| --- | --- | --- | ---: | --- |
| [Queens Botanical Garden](https://queensbotanical.org/calendar/) — Queens | `queens_botanical_garden_ny` | B1 / new | 22 | TEC REST; 43-50 Main Street, Flushing, NY 11355. |
| [Van Cortlandt Park Alliance](https://vancortlandt.org/calendar-of-events/) — Bronx | `van_cortlandt_park_alliance_ny` | B1 / new | 12 | TEC REST; actual garden, playground, Golf House and Nature Center entrances/points; full interior directions retained. |
| [Fort Tryon Park Conservancy](https://forttryonpark.org/events/) — Manhattan | `fort_tryon_park_conservancy_ny` | B1 / new | 26 | TEC REST; reviewed Heather Garden / Margaret Corbin Circle street access, visibly approximate where inferred. |
| [NYC Parks — Staten Island Urban Park Rangers](https://data.cityofnewyork.us/City-Government/NYC-Parks-Public-Events-Upcoming-14-Days/w3wp-dpdi) — Staten Island | `nyc_parks_staten_island_urban_park_rangers_ny` | B2 / new | 6 | Separate exact official upcoming-14-day borough/category subset; five reviewed meeting locations. The broad citywide source is repaired separately in B3 below. |
| [Bronx River Alliance](https://bronxriver.org/visit-the-river/calendar) — Bronx | `bronx_river_alliance_ny` | B3 / new | 6 | Bounded full-detail hydration with native Date/Location/Start/End evidence; actual river-house and park entrances, including preserved meeting directions and visibly approximate access points. |
| [Wave Hill](https://www.wavehill.org/calendar) — Bronx | `wave_hill_ny` | B3 / new | 78 | Custom calendar plus complete program bodies; 4900 Independence Avenue, Bronx, NY 10471, with named interior meeting locations and visibly approximate property access point. |
| [Brooklyn Bridge Park](https://brooklynbridgepark.org/events/) — Brooklyn | `brooklyn_bridge_park_ny` | B3 / new | 44 | Complete public park program evidence and location-specific street/entrance mappings; no generic source-center coordinates. |
| [Greenbelt Conservancy](https://www.eventbrite.com/o/greenbelt-conservancy-10628899098) — Staten Island | `greenbelt_conservancy_staten_island_ny` | B3 / new | 5 | Current official Eventbrite organizer replaces the unavailable sigreenbelt.org website. Five public dated programs retain the complete overview and all native text modules; separate reviewed Nature Center and Nevada Avenue Parking Lot meeting facilities. Three overlapping Parks occurrences are owned by this direct organizer. |
| [NYC Parks — citywide public events, upcoming 14 days](https://data.cityofnewyork.us/resource/w3wp-dpdi.json) — All five boroughs | `municipal_mapsee_0e46855a44eb788f36a2c0ab` | B3 / repair 4603 | 346 | Repair 4603 through the official SODA calendar; all pages and native event bodies, actual reviewed park/facility streets and points. The separately implemented Staten Island Ranger subset retains ownership of its events. |

### Food & Drink

| Official source / calendar | Source key | Batch / action | Captured | Collector and physical-location decision |
| --- | --- | --- | ---: | --- |
| [Sake Studies Center at Brooklyn Kura](https://www.sakestudiescenter.com/calendar) — Brooklyn | `sake_studies_brooklyn_ny` | B1 / new | 15 | Dated JSON-LD plus full class detail bodies; 34 34th Street Industry City Building 6, Brooklyn, NY 11232. |
| [Industry City — public events](https://industrycity.com/events/) — Brooklyn | `municipal_mapsee_f8b8293b927ebc8172bbc1a9` | B2 / repair 3097 | 30 | Native TEC schedule plus complete details and venue-specific streets/points; independently covered Sake Studies events excluded from this source. |

### Family & Kids

| Official source / calendar | Source key | Batch / action | Captured | Collector and physical-location decision |
| --- | --- | --- | ---: | --- |
| [Children’s Museum of Manhattan](https://cmom.org) — Manhattan | `municipal_mapsee_4d60394f1806d3366dd987d3` | B1 / repair 4350 | 144 | TEC REST; recognized museum rooms resolve to 212 West 83rd Street, New York, NY 10024. |
| [Staten Island Children’s Museum](https://sichildrensmuseum.org) — Staten Island | `municipal_mapsee_ff1f81293a6a6ae75a21a2d8` | B1 / repair 4704 | 29 | TEC REST; 1000 Richmond Terrace Building M, Staten Island, NY 10301; building retained within street component. |
| [Queens County Farm Museum](https://www.queensfarm.org/events-calendar/) — Queens | `queens_county_farm_museum_ny` | B1 / new | 58 | TEC REST; 73-50 Little Neck Parkway, Queens, NY 11004. Later exact PAD point correction has separate evidence. |
| [Commonpoint — public Event category](https://www.commonpoint.org) — Queens / Bronx | `municipal_mapsee_8ada9fb25b90788ab8a89a73` | B2 / repair 4370 | 10 | Complete native Event category id 4, with venue-specific addresses. Separately enrolled Class category is outside this clearly labeled scope. |
| [Brooklyn Children’s Museum](https://www.brooklynkids.org/events/) — Brooklyn | `brooklyn_childrens_museum_ny` | B3 / new | 24 | Native Events Manager ICS supplies complete descriptions and dated public program instances; guarded rolling 30-day horizon. 145 Brooklyn Avenue, Brooklyn, NY 11213. |
| [Bronx Zoo — Holiday Lights](https://bronxzoo.com/holiday-lights) — Bronx | `bronx_zoo_holiday_lights_ny` | B3 / new | 28 | Explicit public seasonal dates and full main/FAQ narrative; member previews excluded. 2300 Southern Boulevard, Bronx, NY 10460. Native 1–9pm admission includes the clearly retained 4:30pm lights-on instruction. |
| [New York Aquarium — Holiday Tides](https://nyaquarium.com/holiday-tides) — Brooklyn | `new_york_aquarium_holiday_tides_ny` | B3 / new | 6 | Explicit December 26–31, 11am–3pm festival dates, complete seasonal description; 602 Surf Avenue, Brooklyn, NY 11224. Own venue contact replaces an unrelated organization footer address. |

### Sports & Fitness

| Official source / calendar | Source key | Batch / action | Captured | Collector and physical-location decision |
| --- | --- | --- | ---: | --- |
| [Dyckman Run Club](https://dyckmanrunclub.org/events) — Manhattan / Bronx | `dyckman_run_club_ny` | B1 / new | 11 | Permitted Squarespace full details; 247 Dyckman Street, New York, NY 10034, or Bronx Legends, 1761 Walton Avenue, Bronx, NY 10453. |
| [Riverside Park Conservancy](https://riversideparknyc.org/events/) — Manhattan | `municipal_mapsee_a60c8290b2e794fcd00a52da` | B1 / repair 3767 | 18 | TEC REST; exact Field House/compound/playground street locations, native event points and preserved meeting directions. |
| [Randall’s Island Park Alliance](https://randallsisland.org/events/) — Manhattan | `municipal_mapsee_accd81805a1bc1a57d12e24b` | B1 / repair 3734 | 5 | TEC REST; 11 Wards Meadow Loop Urban Farm or 10 Central Road stadium. Incorrect UTC+0 export clocks require visible local-clock agreement. |
| [Brooklyn Uprising / BKUP](https://www.bkup.nyc/events) — Brooklyn | `bkup_brooklyn_ny` | B3 / new | 66 | Current custom event details and complete participant descriptions; actual gym at 20 John Street and distinct Ritual Moves room at 32 Pearl Street, Brooklyn, NY 11201, each with its reviewed venue point. |
| [NYRR Open Run](https://prod.nyrr.org/open-run) — Multiple boroughs | `nyrr_open_run_ny` | B3 / new | 95 | Current primary run/walk schedules and native meeting maps; bounded explicit recurrence and park-specific street access. Dated source scope and exceptions remain in the captured evidence. |

### Markets, Makers & Shopping

| Official source / calendar | Source key | Batch / action | Captured | Collector and physical-location decision |
| --- | --- | --- | ---: | --- |
| [Materials for the Arts](https://www.materialsforthearts.org/events/) — Queens | `materials_for_arts_ny` | B1 / new | 1 | TEC REST; 33-00 Northern Blvd 3rd Floor, Long Island City, NY 11101. |
| [POWERHOUSE Arena and Columbus Circle](https://powerhousearena.com/events/) — Brooklyn / Manhattan | `powerhouse_arena_ny` | B1 / new | 4 | Events Manager full details; 28 Adams Street, Brooklyn, NY 11201, or 10 Columbus Circle #304, New York, NY 10019. |
| [Grand Bazaar NYC](https://grandbazaarnyc.org/events/) — Manhattan | `grand_bazaar_nyc_ny` | B1 / new | 9 | Complete editorial details, not truncated calendar-export excerpts; 100 West 77th Street, New York, NY 10024. |
| [Greenlight Bookstore](https://greenlightbookstore.com/events) — Brooklyn / Manhattan | `greenlight_bookstore_ny` | B2 / new | 17 | Local full-detail capture verified ten actual streets, but production returned publisher_http_403 and paused this source. Local capture is not a production access receipt; see the operational hold below. |
| [MakerSpace NYC](https://www.makerspace.nyc/classes) — Brooklyn | `makerspace_nyc_ny` | B3 / new | 8 | Official class-page links to verified organizer-owned Eventbrite native data; full summary and all narrative modules. Multi-date classes expand only explicit dates. 140 58th Street Building B Unit 1C, Brooklyn, NY 11220. |

### Gaming & Hobbies

| Official source / calendar | Source key | Batch / action | Captured | Collector and physical-location decision |
| --- | --- | --- | ---: | --- |
| [Wonderville](https://www.wonderville.nyc/events) — Brooklyn | `wonderville_brooklyn_ny` | B1 / new | 52 | Complete native Squarespace bodies; 1186 Broadway, Brooklyn, NY 11221. |
| [Twenty Sided Store](https://twentysidedstore.com/collections/events) — Brooklyn | `twenty_sided_brooklyn_ny` | B1 / new | 43 | Public Shopify product/variant data and complete matching descriptions; dated available individual sessions at 280 Grand Street, Brooklyn, NY 11211. |
| [Sip & Play](https://www.sipnplaynyc.com/general-5) — Brooklyn | `sip_and_play_brooklyn_ny` | B3 / new | 28 | Seven complete official weekly program paragraphs, materialized in a reviewed 28-day window; 471 5th Avenue, Brooklyn, NY 11215. Conflicting clocks and unanchored biweekly series remain held. |
| [NYC Pauper League](https://www.decksandthecity.org/schedule) — Manhattan / Brooklyn | `nyc_pauper_league_ny` | B3 / new | 6 | Independent official organizer’s current season, weekday/time, full rules and explicit holiday breaks; exact Hex Upper West/Union Square and current Brooklyn Strategist streets. Bounded 28-day materialization. |
| [OS NYC](https://www.os-nyc.com/events) — Manhattan | `os_nyc_new_york_ny` | B3 / new | 8 | Actual current Squarespace /events calendar with complete Post Body; 50 Bowery, New York, NY 10013. Sold-out watch party and closures held; unrelated BrookLAN is not assigned this venue. |

### Civic, Volunteering & Community

| Official source / calendar | Source key | Batch / action | Captured | Collector and physical-location decision |
| --- | --- | --- | ---: | --- |
| [Lower East Side Ecology Center](https://www.lesecologycenter.org/calendar/) — Multiple boroughs | `municipal_mapsee_6a0963906d4579496fa3659c` | B1 / repair 3306 | 134 | All TEC pages, complete narratives, actual compost/volunteer locations; streets and native points preserved. |
| [Astoria Park Alliance](https://www.astoriaparkalliance.org/events) — Queens | `astoria_park_alliance_ny` | B1 / new | 1 | Permitted Squarespace detail; Field House near Hoyt Avenue North & 19th Street, Astoria, NY 11102, with visibly approximate meeting-point label. |
| [City Parks Foundation](https://cityparksfoundation.org/calendar/) — All five boroughs | `municipal_mapsee_a5f8d3546bd7cb625105dccf` | B2 / repair 2605 | 40 | Complete TEC pages; full native descriptions verified against all 42 current detail bodies. Twenty-seven actual park locations; two cross-park conflicts held. |
| [NYC Older Adult Center Activities (60+, next 21 days)](https://data.cityofnewyork.us/Social-Services/Older-Adult-Center-OAC-Activities/fzy4-e84j) — Manhattan / Brooklyn / Bronx / Queens | `municipal_mapsee_fa65937887b2c538c7ce242f` | B2 / repair 4602 | 399 | Complete 21-day dated-occurrence SODA query; actual center streets/points, age scope, accessibility and explicit St Nicks cross-site meetings preserved. |
| [Brooklyn Repair Cafe](https://www.repaircafe.nyc/upcoming-events) — Brooklyn | `municipal_mapsee_de7d26035617ddd2af35f829` | B2 / repair 4331 | 1 | Permitted Squarespace complete content; Another World, 629 Nostrand Avenue, Brooklyn, NY 11216. |
| [Brooklyn Community Pride Center](https://www.lgbtbrooklyn.org/calendar) — Brooklyn | `municipal_mapsee_8944f57397b034b9df390cd7` | B2 / repair 4330 | 65 | Official public Wix sitemap/details; durable complete-only hydration and explicit venue/point checks. Distinct from Brooklyn Pride Inc. |
| [New York Irish Center](https://www.newyorkirishcenter.org/events) — Queens | `municipal_mapsee_531e3bb7ca6b8a000c88ee80` | B2 / repair 4588 | 8 | Permitted Squarespace details; 10-40 Jackson Avenue, Long Island City, NY 11101. Offsite departures and unavailable slots require explicit evidence. |
| [Brooklyn Community Board 6](https://brooklyncb6.cityofnewyork.us/events/) — Brooklyn | `brooklyn_community_board_6_ny` | B3 / new | 62 | Current municipal public meeting details, complete participation narrative and actual meeting venue streets/points. |
| [Transportation Alternatives](https://transalt.org/events) — Multiple boroughs | `transportation_alternatives_ny` | B3 / new | 11 | Publisher-linked current Mobilize programs replace the stale embedded 2024 calendar; full native bodies and actual public meeting/volunteer locations. |

## Description, schedule and location contracts

Accepted events carry the complete publisher narrative, not a listing excerpt or generic venue biography. Blank or over-12,000-character bodies are held; descriptions are never clipped to make a record pass. Native category labels, detailed accessibility/age/price statements and ticket or meeting instructions remain in the text. The captures preserve the full normalized descriptions and SHA-256 baselines, including long BPL biographies, Transit policies, maker-class instructions and zoo/aquarium seasonal details.

Existing TEC, ICS, Squarespace, JSON-LD, Shopify, LiveWhale, Localist, Drupal, Wix and municipal SODA normalizers are reused where their data is complete. New source modules bridge the actual publisher-specific gaps. Detail-heavy calendars persist bounded manifests and resume hydration without discarding progress. Incomplete checkpoints emit no publishable partial snapshot; only complete validated snapshots are released. Detail pipelines that require a final manifest reread persist that final step across invocations. Robots policies, exact allowed hosts, normal transport and per-publisher pacing remain in force. Transit’s 10-second delay and Radegast’s 60-second delay have explicit operational treatment.

| Profile or data family | Explicit implemented boundary |
| --- | --- |
| Brooklyn Children’s Museum | Rolling 30-day window from the native 50-row dated ICS. A horizon guard rejects a full feed that ends before the requested window. Closure and member-only notices do not become public programs. |
| BPL Presents | The explicitly named BPL Presents series only, within the reviewed 60-day collection window, at four actual branches. This does not claim the entire BPL branch calendar or either other library system. |
| Transit Museum | Native public museum/station programs with full HTML detail hydration. Four station-tour meetings are visibly approximate, and full ticket-specific instructions remain. Two route-only walks without a publicly identified start location remain held. |
| MakerSpace NYC | Organizer-owned public class links. Multi-date series expand only the dates and clocks explicitly listed in the publisher’s full narrative, within native season bounds. |
| Sip & Play and NYC Pauper League | A fresh primary weekly schedule is revalidated each run before a finite rolling 28-day materialization. Pauper also respects its explicit season end and both holiday breaks. Unknown biweekly anchors and conflicting clocks are not guessed. |
| Zoo and aquarium seasonal programs | Only explicitly advertised public dates. Bronx Zoo member-preview nights and calendar gaps are excluded; its early admission time is retained together with the distinct lights-on instruction. Aquarium days and 11am–3pm window come from its own program page. |
| NYC Parks | The broad upcoming-14-day public-event feed is repaired separately from the already implemented Staten Island Ranger subset. Exact ownership filtering also preserves direct City Parks Foundation, NYRR and Wave Hill ownership and three exact Greenbelt organizer matches. Current record-level missing/conflicting venue or body conditions remain explicit holds. |
| Greenbelt Conservancy | The active public organizer page replaces the unavailable former website. Native organizer and organization identities bind all five listing/detail records; full text modules, actual end times and two distinct official Parks meeting facilities are retained. Ordinary detail hydration resumes through checkpoints and the organizer manifest is compared again before release. |
| Older Adult Center Activities | Complete rolling 21 × 24-hour native query, explicit ages 60+ and actual centers/meetings. Native recurring flags do not fabricate additional dates. The 501st row fails completeness instead of truncating. |
| Commonpoint | Entire native public Event category id 4. The separately enrolled Class category remains outside the explicitly named profile. |
| Fifth Hammer | All dated programs available in the robots-permitted current-month HTML; disallowed export/query routes are not used. |
| NYU and Fordham | Public, local, in-person activities with full native descriptions and real venue identities; virtual/internal/foreign or incomplete records are excluded. Campus addresses are not applied to arbitrary offsite events. |

Full numbered streets preserve Queens hyphens, building names, floor and unit information. Native points, exact NYC Planning PAD matches or expressly reviewed park/station entrances are bound to the source, venue name and full street. The search-area circle never supplies event coordinates. Approximate meeting/access points have visible qualifications and documented provenance; they do not erase the publisher’s interior directions. Narrow New York street forms and reviewed intersections are validated in the database rather than changed into fictional addresses.

The later Commonpoint Bronx correction and NYU Washington Square normalization repair address specific unpublished events. Numbered Bowery, Mount Morris Park West, Reservoir Oval East and Prospect Park West retain narrow borough-specific support and normalized directional forms. Their original captures remain immutable, and the separate correction evidence records the expected differences for final production comparison.

## Concrete remaining publisher and data holds

These are observed access or source-data conditions. Implemented B3 publishers no longer appear as “adapter needed” work. Already-working baseline publishers are not included. Missing attendee information, explicit publisher restrictions and expired schedules are distinct from a parsing success.

### Arts, libraries and family

| Publisher / official route | Current evidence and disposition |
| --- | --- |
| [Greenlight Bookstore](https://greenlightbookstore.com/events) | B2 full HTML capture succeeded, but the deployed ordinary collector received `publisher_http_403` at approximately 23:05 UTC and safely paused the source. Leave paused; local success does not justify changing identity, bypassing the response or reenabling merely to retry. |
| [Queens Museum](https://queensmuseum.org/calendar/?filter=event&sort=date) | Production-identity robots response was HTTP 202, so access permission could not be established. A future permitted response must also resolve the actual park/building entrance. No alternate access workaround was attempted. |
| [New York Public Library](https://www.nypl.org/events/calendar) | Normal allowed page request returned a 212-byte Incapsula/JavaScript challenge shell, not calendar content. No challenge bypass attempted. |
| [Queens Public Library](https://www.queenslibrary.org/calendar) | The robots route redirects to `connect.queenslibrary.org` and returns HTTP 403; ordinary access permission is unestablished. |
| [National Lighthouse Museum](https://lighthousemuseum.org/events/) | Audited native TEC feed contained no still-upcoming occurrence. Recheck when the publisher adds a dated program; no past event is recycled. |
| [Alice Austen House](https://aliceausten.org/events/) | Audited native event feed was empty. A verified future dated schedule is required before activation. |

### Nightlife, food, drink and gaming

| Publisher / official route | Current evidence and disposition |
| --- | --- |
| [Brooklyn Brewery](https://brooklynbrewery.com/events/) | Current homepage says temporarily closed during the move to 1 Wythe Avenue; current events hub has no active future dates. The legacy 79 North 11th Street FAQ is not used as the new venue. |
| [BrookLAN](https://www.brooklan.com/events) | Normal venue route returns 404; remaining [official Eventbrite organizer](https://www.eventbrite.com/o/brooklan-new-york-31064796985) Commander entries are marked postponed. Separately implemented OS NYC is a different venue and calendar. |
| [Hex & Company’s own weekly calendar](https://www.hexnyc.com/hexandcoweeklyevents/) | Normal publisher response presents a SiteGround CAPTCHA. The permitted independent Pauper League source covers its current Upper West Side and Union Square league events; other Hex programming remains behind this access hold. |
| [The Uncommons](https://uncommonsnyc.com/) | Publisher and robots routes present a SiteGround CAPTCHA. Search-index snippets are not a verified production-accessible calendar; no challenge workaround attempted. |
| [Brooklyn Strategist’s Jumbula TCG catalog](https://the-brooklyn-strategist.jumbula.com/tcg-events) | Permitted current catalog contains expired qualifier/prerelease dates; the adult schedule has weekdays without usable clocks. Current Saturday Pauper at 148 Pierrepont Street is covered by its official league. No former 333 Court Street location is reused. |
| [SingleCut Queens](https://www.singlecut.com/tap-room-events) | Native program text names Wednesday movies, Thursday bingo and Friday trivia but omits event clocks. The exact newsletter RSS endpoint advertised by the permitted Elfsight configuration is robots-denied on us20.campaign-archive.com (Disallow: /); no RSS/proxy fetch was attempted. General taproom hours do not establish program start times; out-of-city Barn listings are excluded. |
| [Bar LunÀtico](https://www.barlunatico.com/calendar) | Reviewed query/export route is explicitly disallowed by robots; normal HTML supplies a JavaScript calendar shell without a verified full-event route. No disallowed export used. |
| [The Backyard BX / Bronx Brewery](https://thebackyardbx.com/) | Rechecked current page says public hours are TBD and the schedule is dropping soon. The venue is 856 East 136th Street, Bronx, NY 10454, but no future dated program is supplied; the venue’s existence does not create an event. |
| [Grimm Artisanal Ales](https://grimmales.com/upcoming-events/) | Reviewed normal publisher request returns HTTP 403. No new permitted complete event route has been verified and no access workaround was attempted. |
| [Hudson Table Brooklyn](https://hudsontable.com/brooklyn/calendar/) | Reviewed ordinary cooking-calendar response returns HTTP 403 despite rich indexed class content. The normal permitted collection route is not available. |

### Outdoor, university and civic calendars

| Publisher / official route | Current evidence and disposition |
| --- | --- |
| [NYC permitted-event datasets](https://data.cityofnewyork.us/City-Government/NYC-Permitted-Event-Information/tvpp-9vvx) | Existing registries 4604/4605 remain held. Native times mainly describe setup/breakdown; records lack attendee event links and complete event narratives and include private permits. Organizer-enriched public attendee information is required. |
| [CUNY events](https://events.cuny.edu/) | Current calendar access is explicitly robots-denied. No disallowed list/detail requests are used. |
| [The New School](https://events.newschool.edu/) | Official old detail URLs redirect to `event.newschool.edu`, whose robots request returns HTTP 403. A separate advertised public Algolia alternative uses POST plus app/search-key headers, outside the reviewed GET+Accept transport; no allowed documented GET equivalent was verified. POST is not falsely described as robots-forbidden. |
| [Gowanus Canal Conservancy](https://gowanuscanalconservancy.org/events/) | Robots endpoint returned HTTP 202 on two ordinary checks, leaving access permission unestablished. No detail/registration workaround was used. |
| [NYC Bird Alliance](https://nycbirdalliance.org/events-birding) | Public Neon event-list shell is allowed, but the advertised listing POST `/nx/portal/event-list/list`, RSS `/nx/feed` and Outlook `/nx/publicaccess/outlookCalendar` are denied by `Disallow: /nx/`; the allowed `/nx/portal/neonevents/` exception does not cover them. No POST or disallowed export request was made. |
| [Freshkills Park Alliance](https://freshkillspark.org/upcoming-events) | Current calendar explicitly lists no upcoming programs; latest inspected dates were April 2026. No stale spring occurrence is created. |
| [Socrates Sculpture Park](https://socratessculpturepark.org/) | Inspected public-program calendar has no future program; latest seasonal activity was October 31, 2026. Exhibition/park hours do not fabricate new program dates. |
| [Boys’ Club of New York](https://bcny.org/) | Existing registry 4717 remains `robots_denied`; no alternate identity or blocked route is used. |
| [Brooklyn Pride Inc.](https://brooklynpride.org/events) | Separate organizer from repaired Brooklyn Community Pride Center. The observed 30 June 2026 entries are expired; no current future occurrence was verified. |

## Specific rejected event records

Specific rejected rows do not turn a successfully implemented parent calendar into another enrollment task. Full IDs, reasons, counts and native evidence are preserved in the source captures.

| Record condition | Disposition |
| --- | --- |
| Transit Museum’s two November 21 route walks | Full museum and public ticket pages do not identify a starting street/meeting station. The ticket pages reserve further program information for post-booking email. Keep these two records held; no booking, login or email access was attempted. |
| Transit museum tours at named Grand Central/Penn stations | Full prose supports those specific stations; reviewed public entrance points are visibly approximate and ticket-specific instructions remain intact. These accepted records are distinct from the route-only holds. |
| Commonpoint Hanukkah Festival | Native 01:00 start conflicts with prose 1–3pm; held rather than creating a fourteen-hour family event. |
| NYU missing native full description | Sixty-one of 138 earlier returned items lacked the requested full body. Summaries are not substituted; additional online/foreign/internal/unreviewed records are excluded. |
| City Parks conflicting park identities | Tilden/Tilyou and McKinley/Leif Ericson records identify different parks across title/venue/body. No cross-park guess. |
| Older Adult Center invalid/duplicate/virtual records | Earlier capture held 12 invalid intervals, six conflicting duplicate rows and three virtual/hybrid rows. No invented duration or arbitrary conflicting prose winner. |
| Sip & Play conflicting/unanchored programs | Wednesday Commander header/body conflict, three biweekly groups lack anchors, and Family Fridays is a promotion without a defined occurrence. Their accepted sibling programs use explicit reviewed schedules. |
| Wild East / OS NYC unavailable programs | Closed booking, missing clock, sold-out watch party and closure records remain held. |
| Radegast incomplete/nonpublic records | Hidden/nonapproved, expired, empty/location-only bodies and inverted periods remain held; full native eligible events continue. |
| NYC Parks and CB6 remaining meeting-site records | Broad Parks retains two conflicting Oak Ridge coordinates and two privately withheld Randall’s Island Team RIVER locations. CB6 retains three Agenda TBD committee meetings and one bird walk without a specific Prospect Park meeting site. These record-level conditions do not leave a broad venue-mapping backlog. |
| Other new outdoor/public calendars | Native missing/conflicting times, full bodies, public attendance status or actual meeting locations remain explicit per-record holds in the B3 outdoor capture. Private one-on-one BKUP appointments and undisclosed Mobilize meeting sites remain excluded. No generic venue or source-center substitution. |

## Evidence and release record

The [frozen B1/B2 inventory](REMAINING_SOURCES_20261114.md#verification-evidence-and-release-record) indexes the six earlier captures and location corrections. B3 evidence is:

| B3 group | Full accepted record capture | Research / review |
| --- | --- | --- |
| Arts, library and makers | [73 full records](../../docs/evidence/new-york-arts-final-capture-2026-11-14.json) | [Research](../../docs/evidence/new-york-arts-final-research-2026-11-14.json); [review](../../docs/evidence/new-york-arts-final-review-2026-11-14.md); [two held public ticket-page checks](../../docs/evidence/new-york-arts-final-held-meetings-2026-11-14.json) |
| Social, gaming and Greenbelt organizer | [72 full records](../../docs/evidence/new-york-social-final-capture-2026-11-14.json) | [Research](../../docs/evidence/new-york-social-final-research-2026-11-14.json); [independent Greenbelt review](../../docs/evidence/new-york-greenbelt-independent-review-20261114.json) |
| Outdoors, civic and fitness | [Full capture](../../docs/evidence/new-york-outdoors-final-capture-2026-11-14.json) | [Research](../../docs/evidence/new-york-outdoors-final-research-2026-11-14.json) |
| Zoo and aquarium | [34 full records](../../docs/evidence/new-york-family-final-capture-2026-11-14.json) | [Research](../../docs/evidence/new-york-family-final-research-2026-11-14.json) |
| Specific Commonpoint venue correction | [Exact source/event and point evidence](../../docs/evidence/new-york-commonpoint-location-repair-20261114.json) | Original B2 capture preserved; only the still-unpublished affected row is eligible for targeted refresh. |
| CB6 tree-lighting and Bike Bus meeting locations | [Tree-lighting evidence](../../docs/evidence/new-york-cb6-tree-lighting-location-20261114.json); [Bike Bus evidence](../../docs/evidence/new-york-bike-bus-location-review-20261114.json) | Current official program and address/entrance corroboration preserves the complete original event descriptions and explicitly qualified meeting points. |

Three separate small category onboarding corpora are preserved in the app repository under `docs/evidence/new-york-category-onboarding*`. Expected participant activities were manually frozen before read-only evaluation against the actual production classifier. Unknowns, wrong categories and attribute misses remain in the receipts; this source release does not tune the classifier, add blanket publisher categories or change expectations to match outputs. These purposive engineering samples are not population accuracy estimates.

### Production verification — release owner to append

Append the consolidated collector and backend PR/commit/deployment receipts, guarded migration workflow result, completed source and queue state, source/occurrence deduplication dispositions, actual staged/public counts, full-description and structured-address readback comparisons, and remaining operational holds here. This capture inventory does not independently assert that a local parse was published in production.
