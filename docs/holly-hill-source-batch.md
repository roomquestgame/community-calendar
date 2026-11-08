# Holly Hill complete source batch

Owner request: include every discovered Holly Hill-area source and any relevant MapSee/Udell feeds in one intake batch.

## Scope and accounting

| Inventory group | Count | Treatment |
|---|---:|---|
| Supported new publisher calendars | 12 | Exact parser and source configuration; activation requires guarded transport verification. |
| Additional URL leads | 25 | Registered with an explicit review reason and collection disabled. |
| Venue leads without a verified feed | 5 | Retained in this inventory without a fabricated feed URL. |
| Existing regional sources | 23 | Reuse 19 MapSee identities and four local Chamber/state park identities. |

The catalog audit inspected all 54 MapSee root source configuration files and all 32 catalog/checklist files across the eight Udell city catalogs, including the owned fork. No configured direct feed in the named towns was found. All 19 broader Charleston MapSee sources are included; the three existing pauses are retained without contact. This is configured catalog coverage, not a claim to have enumerated every national-provider event or every historical curation note.

## Supported collectors

| Publisher | Exact feed | Format |
|---|---|---|
| Santee Cooper Country regional events | https://www.santeecoopercountry.org/daily-events-calendar/ | json / jsonld |
| Audubon Beidler Forest public programs | https://www.audubon.org/beidler-forest/explore/seasonal-highlights/night-exploration | html / html |
| South Carolina 250 public calendar | https://southcarolina250.com/events/?ical=1 | ical / ical |
| Town of Eutawville | https://townofeutawville.gov/wp-json/tribe/events/v1/events | json / wordpress |
| Town of Elloree public calendar | https://elloreesc.com/elloree-town-calendar/ | html / html |
| D&G Outdoors public pheasant shoots | https://dandgoutdoors.com/hunt/ | html / html |
| Outside Inn Campground public events | https://outsideinncampground.com/upcoming-events/ | html / html |
| Dorchester County Library — St. George | https://dorchesterlibrarysc.libcal.com/ical_subscribe.php?src=p&cid=22342 | ical / ical |
| Berkeley County Library — Moncks Corner | https://berkeleylibrarysc.libcal.com/ical_subscribe.php?src=p&cid=8209 | ical / ical |
| Orangeburg-Calhoun Technical College continuing education | https://octech.coursestorm.com/browse | html / html |
| Cane Bay Family YMCA | https://ymcagc.org/events/ | html / html |
| Orangeburg County Library | https://www.orangeburgcounty.org/common/modules/iCalendar/iCalendar.aspx?catID=23&feed=calendar | ical / ical |

## Collection contracts

- All publishers use the existing HTTPS, public-address, robots, pacing, response-size and deadline guards. Elloree has one fixed empty-JSON public-calendar POST; callers cannot provide a different host, URL or body.
- St. George and Moncks Corner use their explicit branch identity. Off-site events retain the publisher’s actual venue. Source discovery circles are never used as event coordinates.
- OCTech course ranges become their actual dated sessions. An unavailable required detail rejects the snapshot rather than certifying a partial catalog.
- SC250 uses bounded overlapping ICS exports after its API proved incomplete. Conflicting recurrence descriptions remain occurrence-level holds.
- Vague weekly prose, private bookings, operating hours, placeholder midnight times and inconsistent dates do not generate public occurrences.
- Seven reviewed civic/business calendars use the existing versioned image/details evidence path, including SC250 ICS. OCTech and Cane Bay use factual HTML v2; three ordinary library feeds use the established ICS path. Images remain candidates until the normal media verifier accepts them.
- Existing category classification, address cache/geocoder, manual overrides, cancellation/withdrawal handling, 96-hour source refresh and real-demand rules remain authoritative.

## Held URL inventory

| Publisher | Reason | Evidence |
|---|---|---|
| Angel Oak Stitchery | blocked — Official classes page, but current fetch 403; no verified dated feed. | https://www.angeloakstitchery.com/classes.htm |
| Crosswind Farm | no_direct_calendar — Only public scheduled/private event information; no dated calendar. Tourism-aggregator occurrence has weekday/date conflict requiring review. | https://www.crosswindfarmsc.com/location-hours |
| The Clubhouse | calendar_not_public — Google calendar info@theclubhousehollyhill.com embed 401 and derived public ICS 404 observed by root; /eventlist mainly Facebook. | https://www.theclubhousehollyhill.com/calendar |
| Skynyrd's Grill & Sports Bar | facebook_schedule_only — Official rendered content advertises daily music and Facebook current schedule; direct fetch 403. | https://www.skynyrdsgrillandsportsbar.com/ |
| Copper House | no_public_dated_calendar — Official rendered page offers email updates for events; no dated calendar; direct fetch 403. | https://copperhousehollyhill.com/ |
| Mill Creek Food & Spirits | contact_for_schedule — Music/karaoke most Fridays/Saturdays, contact for schedule. No exact dated occurrence or recurrence generation. | https://www.millcreeksc.com/food__spirit.html |
| Bell's Marina & Resort | private_venue_rental_page — Events page offers private venue rental, not a public schedule. Direct recheck 202 with 177 bytes. | https://bellsmarina.com/events/ |
| Cork & Barrel | blocked_unverified_calendar — Historical 2026 performance on Bandsintown only; no official dated feed verified. | https://corkandbarrel.net/ |
| Black's Camp & Restaurant | blocked_unverified_calendar — Public events known from secondary reporting; current website blocked and no direct calendar verified. | https://www.blackscamp.com/ |
| Rocks Pond Campground & Marina | stale_domain_requires_review — Old Events search title points to wifi.html, not a calendar. Current fetch 465; do not infer closed. | https://www.rockspondcampground.net/ |
| Orangeburg County YMCA | publisher_http_403 — Published December 5 holiday craft event exists; guarded public calendar access remains unverified. | https://columbiaymca.org/events/ |
| Santee Water Park | operating_hours_not_dated_events — Published May31–Aug2 season has ended; opening hours do not constitute event occurrences. | https://columbiaymca.org/locations/santee-water-park/ |
| CORE / Holly Hill Community Center | dated_program_calendar_not_verified — New community center at 1250 Unity Road; no verified public dated program feed. | https://www.coresc.org/ |
| Old Santee Canal Park | recdesk_adapter_required — Official program portal needs verified public POST/detail contract; SCC already carries some dated park programs. | https://oldsanteecanal.recdesk.com/Community/Program |
| World Grits Festival | future_annual_schedule_outside_window — Official April 9–11, 2027 dates outside 60 days; no invented clock times. | https://w.worldgritsfestival.com/index.html |
| Elloree Heritage Museum | current_dated_schedule_not_verified — Most recent verified dated listing September 15 has passed. | https://www.elloreemuseum.org/events |
| Town of Harleyville | current_dated_schedule_not_verified — Published annual/2025 material is not a current calendar. | https://harleyvillesc.gov/town-events |
| Branchville Raylrode Daze Festivul | publisher_timeout — September 24–26, 2026 dates have passed; next public schedule not verified. | https://www.raylrodedazefestivul.com/ |
| Town of Holly Hill | dated_calendar_not_verified — Council recurrence prose is not expanded into inferred dates. | https://hollyhill.sc.gov/ |
| Town of Santee | dated_calendar_not_verified — Calendar shell found; usable dated feed not established. | https://www.townofsantee-sc.org/upcoming-events-calendars |
| Santee National Wildlife Refuge | activities_without_dated_events — Public activities page has no verified dated event feed. | https://www.fws.gov/refuge/santee/visit-us/activities |
| OCTech Library events | public_eligibility_calendar_unverified — Review public eligibility and dated schedule before collecting. | https://libguides.octech.edu/libraryevents |
| SC Works Trident | publisher_api_http_403 — Official events API returned 403; individual library cross-post remains available. | https://scworkstrident.org/events/?tribe_redirected=1 |
| OCTech academic calendar | administrative_calendar — Academic deadlines are not general public programs. | https://catalog.octech.edu/academic-calendar |
| Westbury Farms strawberries | social_schedule_unverified — Town-linked lead retained; no verified machine-readable dated feed. | https://www.facebook.com/westburyfarmsstrawberries |

## Inventory without a verified feed

- **Santee Steak & Seafood Restaurant** (Santee): Regional directory advertises music; no first-party dated calendar verified. Evidence: https://www.santeecoopercountry.org/where-to-eat/p/santee-steak-seafood-restaurant-61f9164c23d3865efb63739b/
- **Clark's Restaurant & Tavern** (Santee): Dining/bar directory only; no event calendar established. Evidence: https://golfsantee.com/dining-entertainment/
- **Cedar Creek Tavern (formerly Oasis Bar & Grill)** (Santee): Directory says new ownership/renovation and opening soon. Current operation and event schedule unverified. Evidence: https://golfsantee.com/dining-entertainment/
- **Cypress Gardens** (Moncks Corner): Individual dated programs already represented by SCC/Moncks Corner Library; standalone publisher feed not established. Evidence: https://www.santeecoopercountry.org/daily-events-calendar/
- **Claflin University public performances** (Orangeburg): Dated performances represented through SCC/SC250; standalone public feed not established. Evidence: https://southcarolina250.com/events/

## Validation and release evidence

Focused fixture tests exercise all twelve central routes, source identity guards, exact times/addresses, bounded complete snapshots, empty feeds, media evidence and Elloree’s transport boundary. The read-only audit retains all 35 runnable-or-paused source rows plus the complete lead inventory.

The local guarded transport audit returned `dns_unavailable` for all 32 eligible attempts, with three existing paused sources skipped. That environment result is not publisher emptiness and does not establish production success. See `docs/evidence/holly_hill_live_audit_local_20261108.json`.

Production transport, deployment and activation receipts are recorded in the reviewed release PR and the backend handoff. Candidate extraction counts are not public event counts.
