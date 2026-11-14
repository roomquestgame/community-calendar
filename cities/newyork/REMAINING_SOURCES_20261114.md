# New York City remaining-source discovery and implementation inventory — 14 November 2026

This report consolidates the first and second NYC batches. It records **39 implemented source profiles: 26 additions and 13 repairs of sources that had no active public events in the baseline**. Batch 1 contains 23 additions and five repairs; Batch 2 contains three additions and eight repairs. All five boroughs are represented. Each source key appears once below, under a primary category from the requested discovery framework; many calendars serve several categories.

**Counts in this inventory are captured eligible occurrences.** Each capture has its own dated window and evidence hashes. The production-verification section is reserved for deployment receipts and live readback maintained by the release owner. Local successful parsing and a published production event are separate verification steps.

Food Bank for New York City, Brooklyn Bird Club and Scandinavia House already had working public events at baseline. They are excluded from the 39-source cohort, registration changes and remaining-work tables. B2 implementations supersede older discovery notes that had listed City Parks Foundation, NYU, Commonpoint, Bronx Museum, Greenlight, New York Irish Center, Brooklyn Repair Cafe, Industry City or Brooklyn Community Pride Center as work still to implement.

## Implemented source inventory

`B1` and `B2` identify the consolidated release batch. A repair retains its existing source key and numeric registry ID. TEC means the publisher’s native The Events Calendar REST API. Full evidence files are linked at the end.

### Nightlife & Social

| Official source / calendar | Source key | Batch / action | Captured | Collector and physical-location decision |
| --- | --- | --- | ---: | --- |
| [Chilo’s](https://www.chilosbk.com/eventscalendar) — Brooklyn | `chilos_brooklyn_ny` | B1 / new | 5 | Squarespace HTML; 323 Franklin Avenue, Brooklyn, NY 11238. |
| [Forever Brewing](https://www.foreverbrewing.com/events-calendar) — Brooklyn | `forever_brewing_brooklyn_ny` | B1 / new | 19 | Squarespace HTML; 574 President Street, Brooklyn, NY 11215. Native calendar clocks checked against visible local times. |
| [Fifth Hammer Brewing](https://www.fifthhammerbrewing.com/fifth-hammer-calendar) — Queens | `fifth_hammer_queens_ny` | B1 / new | 18 | Permitted current-month Squarespace HTML; 10-28 46th Avenue, Long Island City, NY 11101. |
| [Starr Bar](https://www.starrbar.com/events) — Brooklyn | `starr_bar_brooklyn_ny` | B1 / new | 8 | Complete native Squarespace bodies; 214 Starr Street, Brooklyn, NY 11237. |
| [Skinny Dennis](https://skinnydennisbrooklyn.com/calendar) — Brooklyn | `skinny_dennis_brooklyn_ny` | B1 / new | 21 | Squarespace HTML; 152 Metropolitan Avenue, Brooklyn, NY 11249. |
| [Kills Boro Brewing Co.](https://killsboro.com/events) — Staten Island | `kills_boro_staten_island_ny` | B1 / new | 18 | HTML event JSON-LD matched to complete visible paragraphs; 814 Richmond Terrace, Staten Island, NY 10301. |

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

### Outdoor & Active

| Official source / calendar | Source key | Batch / action | Captured | Collector and physical-location decision |
| --- | --- | --- | ---: | --- |
| [Queens Botanical Garden](https://queensbotanical.org/calendar/) — Queens | `queens_botanical_garden_ny` | B1 / new | 22 | TEC REST; 43-50 Main Street, Flushing, NY 11355. |
| [Van Cortlandt Park Alliance](https://vancortlandt.org/calendar-of-events/) — Bronx | `van_cortlandt_park_alliance_ny` | B1 / new | 12 | TEC REST; actual garden, playground, Golf House and Nature Center entrances/points; full interior directions retained. |
| [Fort Tryon Park Conservancy](https://forttryonpark.org/events/) — Manhattan | `fort_tryon_park_conservancy_ny` | B1 / new | 26 | TEC REST; reviewed Heather Garden / Margaret Corbin Circle street access, visibly approximate where inferred. |
| [NYC Parks — Staten Island Urban Park Rangers](https://data.cityofnewyork.us/City-Government/NYC-Parks-Public-Events-Upcoming-14-Days/w3wp-dpdi) — Staten Island | `nyc_parks_staten_island_urban_park_rangers_ny` | B2 / new | 6 | Separate exact official upcoming-14-day borough/category subset; five reviewed meeting locations. Broad citywide source remains unresolved. |

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

### Sports & Fitness

| Official source / calendar | Source key | Batch / action | Captured | Collector and physical-location decision |
| --- | --- | --- | ---: | --- |
| [Dyckman Run Club](https://dyckmanrunclub.org/events) — Manhattan / Bronx | `dyckman_run_club_ny` | B1 / new | 11 | Permitted Squarespace full details; 247 Dyckman Street, New York, NY 10034, or Bronx Legends, 1761 Walton Avenue, Bronx, NY 10453. |
| [Riverside Park Conservancy](https://riversideparknyc.org/events/) — Manhattan | `municipal_mapsee_a60c8290b2e794fcd00a52da` | B1 / repair 3767 | 18 | TEC REST; exact Field House/compound/playground street locations, native event points and preserved meeting directions. |
| [Randall’s Island Park Alliance](https://randallsisland.org/events/) — Manhattan | `municipal_mapsee_accd81805a1bc1a57d12e24b` | B1 / repair 3734 | 5 | TEC REST; 11 Wards Meadow Loop Urban Farm or 10 Central Road stadium. Incorrect UTC+0 export clocks require visible local-clock agreement. |

### Markets, Makers & Shopping

| Official source / calendar | Source key | Batch / action | Captured | Collector and physical-location decision |
| --- | --- | --- | ---: | --- |
| [Materials for the Arts](https://www.materialsforthearts.org/events/) — Queens | `materials_for_arts_ny` | B1 / new | 1 | TEC REST; 33-00 Northern Blvd 3rd Floor, Long Island City, NY 11101. |
| [POWERHOUSE Arena and Columbus Circle](https://powerhousearena.com/events/) — Brooklyn / Manhattan | `powerhouse_arena_ny` | B1 / new | 4 | Events Manager full details; 28 Adams Street, Brooklyn, NY 11201, or 10 Columbus Circle #304, New York, NY 10019. |
| [Grand Bazaar NYC](https://grandbazaarnyc.org/events/) — Manhattan | `grand_bazaar_nyc_ny` | B1 / new | 9 | Complete editorial details, not truncated calendar-export excerpts; 100 West 77th Street, New York, NY 10024. |
| [Greenlight Bookstore](https://greenlightbookstore.com/events) — Brooklyn / Manhattan | `greenlight_bookstore_ny` | B2 / new | 17 | Drupal monthly listing and full details; ten actual onsite/offsite streets, with structured HTML addresses replacing malformed JSON-LD venue concatenations. |

### Gaming & Hobbies

| Official source / calendar | Source key | Batch / action | Captured | Collector and physical-location decision |
| --- | --- | --- | ---: | --- |
| [Wonderville](https://www.wonderville.nyc/events) — Brooklyn | `wonderville_brooklyn_ny` | B1 / new | 52 | Complete native Squarespace bodies; 1186 Broadway, Brooklyn, NY 11221. |
| [Twenty Sided Store](https://twentysidedstore.com/collections/events) — Brooklyn | `twenty_sided_brooklyn_ny` | B1 / new | 43 | Public Shopify product/variant data and complete matching descriptions; dated available individual sessions at 280 Grand Street, Brooklyn, NY 11211. |

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

## Coverage boundaries and ingestion decisions

### Complete descriptions and dated occurrences

Every accepted record requires the complete publisher narrative, a real venue name and a full street location including city/borough, NY and ZIP. Publication also requires a venue-specific point supplied by the publisher, official location review or the ordinary geocoder. The later exact-point repair evidence supplements first-batch captures whose numbered addresses still needed geocoding. Empty bodies remain held. Source adapters avoid the shared 2,000-character display default and retain full descriptions up to 12,000 characters; over-limit bodies are held without clipping. The evidence captures contain full accepted descriptions and their hashes. Listing snippets, image-only posters, generic venue biographies and invented promotional text are not substitutes for event descriptions.

TEC, permitted Squarespace HTML, native JSON-LD, Shopify variants, LiveWhale JSON, Drupal HTML and public Wix sitemap/detail pages reuse existing normalizers wherever practical. Detail-heavy sources emit a snapshot only when their bounded manifest is complete. The Astoria/Dyckman checkpoint correction preserves the local `YYYY-MM-DD` window, an immutable time anchor and a durable completed cursor before staging; retries can replay the completed snapshot. Publisher robots policies, host checks, ordinary transport and crawl pacing remain in place.

### Explicit calendar scopes

| Source | Implemented coverage | Scope still outside this profile |
| --- | --- | --- |
| NYC Older Adult Center Activities | Complete rolling **21 × 24-hour** query, interpreted in America/New_York; all 420 native rows at the capture, 399 accepted. Source label identifies **ages 60+**. Each native dated occurrence is used as provided. | Dates after the rolling window; virtual/hybrid rows; invalid time intervals and conflicting duplicate occurrences. The `isrecurring` field never fabricates additional dates. A 501st row triggers a completeness failure instead of truncation. |
| NYC Parks — Staten Island Urban Park Rangers | Separately named **upcoming 14-day** subset: native park ID starts with R and native category includes Urban Park Rangers. Seven current native records, six accepted. | The original citywide Parks source remains separately registered and unresolved; the full feed had 444 captured records at 201 native locations. The new subset does not claim a completed citywide repair. |
| Commonpoint public events | Entire native **Event category id 4**: 11 records, 10 accepted. | The separate enrolled **Class** category; mixed Event/Class output had 1,863 records over 38 pages. Restricting an explicitly named public category avoids arbitrary page truncation. |
| Fifth Hammer Brewing | Every dated event available in the publisher’s permitted current-month HTML. | Robots-disallowed export and query-pagination routes. |
| NYU Open to the Public | Requested full native description and exact reviewed NYC venue identity/point. Official JSON repairs the invalid-UTF-8-folding ICS path. | Missing full-body fields, internal/online/foreign activities, unreviewed venues, external destination links and untimed records. |
| Industry City | Public physical programs at their actual venue streets and points. | Sake Studies Center events already collected by its dedicated source; conflicting or unresolved meeting locations. |

Older adult age eligibility is documented by [NYC Aging’s official Older Adult Centers page](https://www.nyc.gov/site/dfta/services/older-adult-center.page). Native age/accessibility/participation statements remain intact; source labels identify the audience without adding prose to event descriptions.

### Street resolution and point precision

Numbered publisher streets are normalized without removing meaningful building, floor, hyphenated Queens number or unit information. Examples include `1000 Richmond Terrace Building M`, `175 Delancey Street 4th Floor`, and `73-50 Little Neck Parkway`. Cooper Square, Washington Square, Grand Concourse, Broadway and Union Turnpike receive narrow New York address handling rather than fictional street suffixes.

Park entrances with genuine intersections or named street segments use exact source-key + venue-name + address + coordinate bindings. An intersection from another source, a changed venue label or a different point does not inherit the exception. Approximate park access is labeled in the public venue name and its provenance; full publisher meeting directions remain in the description. The citywide selection circle never supplies event coordinates.

City Parks’ Little Bay entry preserves the publisher’s explicit 14-18 Utopia Parkway directions and visibly approximates its point using the nearby official PAD match. Glenwood Landing retains the original 39th Avenue prose while visibly approximating access at the venue header’s 39th Road and the official named-garden point. These are documented location inferences under the requested educated-guess allowance. They do not resolve the two contradictory different-park records, which stay held.

## Remaining source work — unresolved publishers and feeds only

The tables below contain unimplemented candidates or genuinely unresolved source identities. Previously implemented B1/B2 sources do not reappear as source-level work. “Implementation needed” identifies a feasible engineering follow-up; an access hold, missing schedule or missing source content is a different blocker. Official URLs are the discovery starting points, and the linked evidence records the observed response or data condition.

### Arts, family, makers and cultural venues

| Candidate / official URL | Observed blocker and concrete next work |
| --- | --- |
| [Queens Museum](https://queensmuseum.org/calendar/?filter=event&sort=date) | Robots endpoint returned HTTP 202 under the production identity, so permission could not be established. The park/building address also needs a reviewed street entrance. Wait for permitted access, then hydrate full detail and occurrence-specific schedules; no access workaround was used. |
| [New York Transit Museum](https://www.nytransitmuseum.org/programs/) | All 27 audited native TEC event descriptions were blank. Build bounded permitted detail hydration, preserve mixed museum/remote/offsite meeting locations and reject incomplete rows. |
| [National Lighthouse Museum](https://lighthousemuseum.org/events/) | Audited TEC feed had no still-upcoming occurrence. Recheck for a newly published dated program before enrollment. |
| [Alice Austen House](https://aliceausten.org/events/) | Tested native event feed was empty. Confirm an active future schedule; no occurrences inferred from past events. |
| [MakerSpace NYC](https://www.makerspacenyc.com/) | External ticket/class links discovered; complete direct feed and occurrence-specific locations still unverified. Review permitted ticket/detail data and each actual workshop site. |
| [Flushing Town Hall](https://www.flushingtownhall.org/events) | Active custom calendar discovered; full-content, date and venue extraction needs an independently verified adapter. |
| [Brooklyn Children’s Museum](https://www.brooklynkids.org/events/) | Custom WordPress schedule requires occurrence-aware detail extraction. Verify public timed program instances and full narrative before registering. |

### Nightlife, food, drink, gaming and recurring venue schedules

| Candidate / official URL | Observed blocker and concrete next work |
| --- | --- |
| [Bar LunÀtico](https://www.barlunatico.com/calendar) | Normal calendar HTML renders its events through JavaScript; query/JSON exports are explicitly disallowed by robots. Find an allowed public detail-discovery route with complete narratives. |
| [The Brooklyn Strategist](https://thebrooklynstrategist.com/) | Current primary site moved to 148 Pierrepont Street; the old 333 Court Street address is stale. Embedded Google ICS is disallowed. Review the official [Jumbula TCG events](https://the-brooklyn-strategist.jumbula.com/tcg-events) page through permitted HTML. |
| [Hex & Company](https://www.hexnyc.com/hexandcoweeklyevents/) | Weekly TCG pages cover several branches, while the special calendar is incomplete/JavaScript dependent. Verify dated sessions and branch identity; keep 2911 Broadway, 1462 First Avenue and 801 Broadway separate. |
| [The Uncommons](https://uncommonsnyc.com/) | Primary response was minimal/JavaScript dependent. MTG programming exists, but a current finite dated calendar and verified physical address need an allowed collector route. |
| [Sip & Play](https://www.sipnplaynyc.com/general-5) | Official Wix recurring-event and Discord announcements do not yet provide a verified finite dated feed. Build only from the real organizer’s calendar, with explicit date/clock evidence. |
| [BrookLAN](https://www.brooklan.com/events) | Official event hub and [Eventbrite organizer](https://www.eventbrite.com/o/brooklan-new-york-31064796985) are active. The original Squarespace assumption was wrong; verify the actual public HTML/ticket format. |
| [Wild East Brewing](https://www.wildeastbrewing.com/) | Current taproom text includes first-Wednesday trivia, but no complete finite structured schedule or address extraction has been implemented. Review explicit dates, time and holiday/cancellation treatment. |
| [Radegast Hall](https://radegasthall.com/) | Custom WordPress frontend advertises live events and Tuesday trivia. Verify its actual public calendar endpoint and complete descriptions instead of assuming a TEC export. |
| [Brooklyn Brewery](https://brooklynbrewery.com/events/) | Active official event hub; native WP/TEC endpoint and full-content mappings remain unverified. |
| [SingleCut](https://www.singlecut.com/tap-room-events) | Queens announcements identify Wednesday movies, Thursday bingo and Friday trivia but omit explicit clocks. Verify dates/times and keep the out-of-city Barn location separate. |
| [Bronx Alehouse](https://www.bronxalehouse.com/weekly-events) | Official weekly imagery advertises Tuesday 7pm trivia at 216 West 238th Street. A validated bounded recurrence collector and exception handling are still needed before materializing dates. |
| [The Bronx Brewery / The Backyard BX](https://thebackyardbx.com/) | Official Bronx programming route sends visitors to Backyard/social pages; the lineup says coming soon. No future dated program is currently verified. |
| [Grimm Ales](https://grimmales.com/upcoming-events/) | Ordinary requests returned 403 and the dated page showed no upcoming events, despite recurring DJ/jam/run-club information. Need permitted transport and current dated evidence. |
| [Hudson Table Brooklyn](https://hudsontable.com/brooklyn/calendar/) | Current cooking-class pages contain rich menus and descriptions, but ordinary requests returned 403. Establish an allowed public transport/API route before integrating. |

### Outdoors, fitness, universities and community calendars

| Candidate / official URL | Observed blocker and concrete next work |
| --- | --- |
| [NYC Parks — full citywide public calendar](https://data.cityofnewyork.us/City-Government/NYC-Parks-Public-Events-Upcoming-14-Days/w3wp-dpdi) | Existing key `municipal_mapsee_0e46855a44eb788f36a2c0ab`, registry 4603, remains unresolved. Typed URL fields and timezone semantics are now understood. The full captured feed has 201 distinct locations requiring source-specific street/entrance review, plus event-level data and access filters. A separate Staten Island Ranger subset is implemented above. |
| [NYC permitted event data](https://data.cityofnewyork.us/City-Government/NYC-Permitted-Event-Information/tvpp-9vvx) | Registry 4604/4605 remain held. Official schema describes start/end predominantly as setup/breakdown; records lack attendee event links and full event descriptions and include private birthday parties. Timezone or query-URL repair alone is insufficient. Organizer-enriched public-event evidence is required. |
| [Fordham University](https://calendar.fordham.edu/) | Current Localist API reported 239 records across three pages. Fetch all pages, filter public/in-person/local activities and resolve actual campus buildings. Avoid also enrolling the older now.fordham.edu calendar as a duplicate. |
| [Bronx River Alliance](https://bronxriver.org/visit-the-river/calendar) | Active custom WordPress program calendar. Full detail pages have Date/Location/Start/End tables; list excerpts are incomplete. Build bounded hydration and location mappings, including Concrete Plant Park at 1370 Westchester Avenue, Bronx, NY 10472; exclude virtual meetings. |
| [Wave Hill](https://www.wavehill.org/calendar) | Active garden/family/culture calendar. Verify full custom details and the official visitor-point mapping for 4900 Independence Avenue, Bronx, NY 10471 before integration. |
| [Freshkills Park Alliance](https://freshkillspark.org/calendar) | No current future occurrence was verified in the inspected upcoming view. Indexed April 2026 events are past. Recheck [upcoming events](https://freshkillspark.org/upcoming-events) for a native dated schedule. |
| [Greenbelt Conservancy](https://sigreenbelt.org/) | Previously known direct site returned 404. Programs exist through NYC Parks/Eventbrite, but a stable permitted direct list/detail source remains unverified. |
| [NYRR Open Run](https://prod.nyrr.org/open-run) | Current official Astoria information gives a Saturday 9am run/walk and meeting map. Verify native dated registrations or an explicit bounded recurrence/exception policy before creating future instances across all five boroughs. |
| [Brooklyn Bridge Park](https://brooklynbridgepark.org/events/) | Active park education/fitness calendar discovered. Registry duplicate audit, complete detail parsing and venue-specific meeting review remain. |
| [Brooklyn Uprising / BKUP](https://www.bkup.nyc/events) | Active custom-rendered fitness/community calendar at 20 John Street, Brooklyn, NY 11201. Complete detail extraction and exact address/point verification remain. |
| [CUNY public events](https://events.cuny.edu/) | Large mixed public/student-only multi-college calendar; about 24 listing pages were observed. Needs audience/virtual filtering, bounded complete hydration and campus-specific venue mapping. |
| [The New School](https://events.newschool.edu/) | Current pages route to event.newschool.edu/Splash. Verify the current public format and audience scope; the former Localist implementation cannot be assumed. |
| [Transportation Alternatives](https://transalt.org/events) | Embedded Squarespace schedule appeared stale from 2024 while current activities use Mobilize. Discover and validate the organizer’s current authorized Mobilize source. |
| [Socrates Sculpture Park](https://socratessculpturepark.org/) | Only near-ending exhibition/season information was verified; no durable new future program series was confirmed for activation. |
| [Gowanus Canal Conservancy](https://gowanuscanalconservancy.org/events/) | Custom WordPress plus Eventbrite/Salesforce registration; complete future list/detail data remain unverified. Volunteer locations must be actual meeting sites, not the office. |
| [Brooklyn Community Board 6](https://brooklyncb6.cityofnewyork.us/events/) | Municipal meeting/neighborhood calendar needs current timed details, public/civic scope filtering and actual meeting addresses. |
| [NYC Bird Alliance](https://nycbirdalliance.org/events-birding) | Active outings with NeonCRM registrations; establish a permitted stable listing/detail flow and complete meeting-location mapping. Distinct from the already-working Brooklyn Bird Club. |
| [Boys’ Club of New York](https://bcny.org/) | Existing registry 4717/key `municipal_mapsee_e310d4f637880c90ca0beecd` is held for `robots_denied`. No disallowed endpoint or alternate access workaround was used. |
| [Brooklyn Pride Inc.](https://brooklynpride.org/events) | Distinct organizer from Brooklyn Community Pride Center. Current listing contained 30 expired June 2026 events and no upcoming program; do not treat the Community Pride Center repair as a repair of this separate source. |

## Event-level holds within implemented profiles

These are specific rejected records, not duplicate source-level enrollment tasks. Their parent calendars are listed only in the implemented inventory. Full held IDs, reasons and native records are retained in the evidence files.

| Profile / record condition | Disposition |
| --- | --- |
| City Parks: Tilden/Tilyou Playground and McKinley/Leif Ericson Park conflicts | Two current records held because venue/title/body identify different parks. No cross-park location guess. |
| Older Adult Activities: 12 invalid intervals, 6 conflicting duplicate native rows, 3 virtual/hybrid rows | Twenty-one native rows held. The 6 duplicates represent 3 dated Aerobics occurrences; no arbitrary prose winner, inferred AM/PM or invented duration. |
| Staten Island Rangers: Discovery Hike—Urban Mammals | One current occurrence held because registration is closed. |
| Commonpoint: Hanukkah Festival | Native start 01:00 conflicts with prose 1–3pm. One event held; no fourteen-hour family event created. |
| NYU: missing full bodies and unreviewed/public-scope violations | Sixty-one of 138 returned items lacked the requested full description; summaries were not promoted. Additional online/foreign/internal/unreviewed records are excluded or held. |
| Greenlight: Fantasy Book Group Location TBD, Small Business Saturday, holiday stroll | One undecided offsite location and two untimed/all-day records held. No bookstore address or time invented. |
| First-batch arts: closure/member/virtual cards, unresolved offsite rooms and undivided multi-day seasons | Public timed occurrences only; full detail-specific decisions remain in arts capture/review evidence. |
| Dyckman and park calendars: blank details, members-only programs, stale workout body on Medal Party, wrong/missing clocks or meeting points | Individual records remain held while verified dated occurrences proceed. |
| Social repairs: unresolved outing departure points, unavailable appointment slots, conflicting schedules and venue mappings | Specific holds remain in the complete second-batch social capture. Source-level repairs are retained in the implemented inventory. |

## Verification evidence and release record

### Captures and research

| Area / batch | Compact research | Full event capture / additional evidence |
| --- | --- | --- |
| Arts, family and markets / B1 | [Arts research](../../docs/evidence/new-york-arts-research-2026-11-14.json) | [Full capture](../../docs/evidence/new-york-arts-capture-2026-11-14.json); [exact point repair](../../docs/evidence/new-york-arts-point-repair-20261114.json); [review](../../docs/evidence/new-york-arts-review-2026-11-14.md) |
| Nightlife, food and gaming / B1 | [Nightlife research](../../docs/evidence/new-york-nightlife-research-2026-11-14.json); [broad discovery](../../docs/evidence/new-york-nightlife-discovery-20261114.json) | [Full capture](../../docs/evidence/new-york-nightlife-20261114.json); [venue points](../../docs/evidence/new-york-nightlife-venue-points-20261114.json) |
| Outdoors, fitness and volunteering / B1 | [Outdoors research](../../docs/evidence/new-york-outdoors-research-2026-11-14.json) | [Full capture](../../docs/evidence/new-york-outdoors-live-capture-2026-11-14.json) |
| Arts/public-program repairs / B2 | [Remaining arts research](../../docs/evidence/new-york-arts-remaining-research-2026-11-14.json) | [Full capture](../../docs/evidence/new-york-arts-remaining-capture-2026-11-14.json); [review](../../docs/evidence/new-york-arts-remaining-review-2026-11-14.md) |
| Social/community repairs / B2 | [Remaining social research](../../docs/evidence/new-york-social-remaining-research-2026-11-14.json) | [Full capture](../../docs/evidence/new-york-social-remaining-capture-2026-11-14.json); [venue points](../../docs/evidence/new-york-social-venue-points-20261114.json) |
| Municipal/volunteer repairs / B2 | [Remaining outdoors research](../../docs/evidence/new-york-outdoors-remaining-research-2026-11-14.json) | [Full capture](../../docs/evidence/new-york-outdoors-remaining-live-capture-2026-11-14.json) |

First-batch captures contain 790 eligible occurrences across 28 source profiles. B2 captures contain 66 arts/public-program occurrences, 104 social/community occurrences and 445 municipal/volunteer occurrences: 615 in total. Together the six capture groups document 1,405 source occurrences across 39 profiles, before live expiration and cross-source deduplication. These are timestamped parser-evidence counts; live production counts are maintained separately. The social capture is anchored at 22:58:44 UTC, so its Industry City count includes a November 14 market that expires at 23:00 UTC. Source-level catalog guards enforce the exact old ID/key/URL/kind/adapter for repairs and refuse an active lease or a source that has started publishing successfully. The Socrata host exception is limited to the explicitly reviewed municipal dataset identities.

Production release work stays consolidated: collector changes, source registration and normal category processing are batched; no per-source PR or workflow dispatch is required. Complete descriptions, structured street locations and location points are checked before staging and again against live public readback.

### Production verification — release owner to append

Append the final collector/deployment commit, batched migration receipt, completed-source counts, staged/public readback totals, description/address hash comparison, remaining operational holds and any deduplication/classification exclusions here. This research inventory does not independently assert a completed production deployment.
