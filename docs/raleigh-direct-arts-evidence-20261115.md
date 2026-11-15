# Raleigh direct arts and community calendars — 2026-11-15

## Scope and results

This adapter covers four primary publishers for the frozen **2026-11-15 through 2027-01-13** window, inclusive in `America/New_York`. It reads complete public calendars before returning any events for staging. Every HTTP operation uses the worker's injected robots-aware, paced transport. The Artspace exception is a narrowly validated public month-display operation; it grants no general POST capability.

| Source key | Exact registered page | Native collection | Native rows in window | Accepted occurrences | Held |
| --- | --- | --- | ---: | ---: | ---: |
| `municipal_dfbc4fd7bb8cf284b5c0856d` | https://www.naturalsciences.org/calendar/ | Published Tribe REST, both pages | 96 | 83 | 13 |
| `downtown_cary_park_nc` | https://downtowncarypark.com/calendar | Both native FullCalendar sources and all 86 detail pages | 86 | 85 | 1 |
| `artspace_raleigh_nc` | https://artspacenc.org/calendar/ | November, December, January MEC tiles and canonical WordPress content | 22 | 16 | 6 |
| `raleigh_little_theatre_nc` | https://raleighlittletheatre.org/shows-and-events/ | Complete native index, three overlapping program pages | 3 programs | 49 | 0 |

Total: **233 accepted occurrences**. All four sources use `html/html`, the above timezone, manifest cap 200, occurrence cap 500, checkpoint cap 850,000 bytes, and a four-hour snapshot lifetime. Descriptions over 12,000 characters fail visibly; they are never silently truncated. Unknown clocks/streets are held with diagnostics.

The complete offline replay uses captured publisher responses, not a production-fetch simulation. Capture HTTP 200 demonstrates access from the research environment only. Production may independently return a block. That block must pause the source without alternate-UA, proxy, browser, or endpoint workarounds. No Visit Raleigh requests were made during this primary-source implementation.

## Natural Sciences: repair existing identity 134

The registry already contains source 134, `municipal_dfbc4fd7bb8cf284b5c0856d`, previously paused for `redirect_blocked` at `https://naturalsciences.org/calendar/events/?ical=1`. Reuse that identity through the guarded migration; do not create a duplicate or alter the active NC State, NCMA, or DNCR adapters.

The independently advertised canonical calendar is https://www.naturalsciences.org/calendar/. Its robots and calendar returned 200. The current advertised ICS (`https://www.naturalsciences.org/calendar/?ical=1`) returned a valid empty calendar; it cannot provide complete coverage.

The page advertises https://www.naturalsciences.org/calendar/wp-json/tribe/events/v1/. Its documented `/events` route is:

`https://www.naturalsciences.org/calendar/wp-json/tribe/events/v1/events`

The adapter supplies `start_date=2026-11-15 00:00:00`, `end_date=2027-01-13 23:59:59`, `per_page=100`, and sequential `page`. The server caps each page at 50: total96, total_pages2, lengths50 and46. Both totals must remain stable; every native ID must be unique and every reported page must be collected.

Native `start_date`/`end_date`, `utc_start_date`/`utc_end_date`, and `timezone=America/New_York` must agree. No synthetic recurrence or all-day midnight time is admitted. Full `description` is retained. Native featured images or event-body images are accepted only from the same publisher's upload path.

Accepted native venues:

| Venue | Street | Native coordinates |
| --- | --- | --- |
| Downtown Raleigh / Nature Exploration Center | 11 West Jones Street, Raleigh, NC 27601 | 35.7822735, -78.6395502 |
| Nature Research Center | 121 West Jones Street, Raleigh, NC 27601 | 35.7822405, -78.6409677 |
| Prairie Ridge | 1671 Gold Star Drive, Raleigh, NC 27607 | 35.812182885871, -78.713963528554 |
| North Carolina Museum of Art | 2110 Blue Ridge Rd, Raleigh, NC 27607 | none; street pending geocode |

NCMA's native venue supplies street/city/ZIP but omits state. Only that exact known NCMA venue identity receives the reviewed NC state component; there is no generic state or venue fallback. NCMA is already an active independent primary source and is not re-onboarded here.

Twelve Whiteville occurrences are outside Raleigh-area scope. One educator paddling trip identifies only the generic “In the Field” venue and has no complete native street, so it is held. No museum default point is attached to field trips. Eighty-one accepted events retain native venue coordinates; two NCMA rows await street geocoding. Sixty-nine accepted events have a native image. Longest retained narrative: 2,105 characters.

## Downtown Cary Park: two calendars, complete detail hydration

Robots and https://downtowncarypark.com/calendar returned200. Its own FullCalendar configuration lists both:

- https://downtowncarypark.com/wp-json/nmc-feeds/v1/events
- https://downtowncarypark.com/wp-json/nmc/eventbrite/v1/fullcalendar

The browser's native `start`/`end` parameters are required. Use local midnight November15 through exclusive local midnight January14, with their actual offset. Responses contain49 and40 rows. Three January14 rows are outside the inclusive local window, leaving86 unique canonical detail URLs. Every one of those86 pages was captured successfully. The adapter does not mistake the two feed lists for full descriptions.

Editorial program pages place prose after `.nmc-block--masthead` in `.gutenberg`; recreation details put prose in `.masthead_intro`. Both complete forms survive, including native preparation, registration and accessibility text. Social-navigation blocks are removed. The visible detail date/time must equal the native API timestamp; conflicting clocks are held.

Every detail page contains the publisher's Organization PostalAddress: **327 S. Academy St., Cary, NC27511**. Onsite park programs must identify Downtown Cary Park or a DCP subvenue; their exact native subvenue name is retained. The park's main address is not assigned to nearby market listings.

Six Cary Farmers Market/Holiday Market rows use **160 E Park Street, Cary, NC27511**, the organizer's explicit permanent navigation address on https://www.caryfarmersmarket.com/plan-your-visit/. This mapping requires the exact canonical market URL pattern/title, native venue East Park Street, and body explicitly placing the market along that street. Moved, relocated, Town Hall, or offsite wording is rejected. These rows carry `reviewed_primary_organizer_street_pending_geocode` and the organizer page as evidence. The ZIP comes from the native Cary calendar; no point is synthesized.

One live-music entry still has no venue field and is held. Forty-five accepted events have a native header image. Longest retained narrative:1,672 characters.

## Artspace: exact public month renderer

Robots at https://artspacenc.org/robots.txt returned200 and exposes an empty `Disallow` for `User-agent: *`. Calendar returned200. Public robots permit the renderer path; no block is bypassed.

The page's own MEC tile shortcode4523 settings and public JavaScript describe month navigation:

https://artspacenc.org/wp-content/plugins/modern-events-calendar-lite/assets/js/frontend.js

The public `mecTileView` month handler POSTs to **https://artspacenc.org/wp-admin/admin-ajax.php** with:

- `action=mec_tile_load_month`
- `mec_year`, `mec_month`
- the published `atts[...]` form fields
- fixed `apply_sf_date=0`, `navigator_click=1`

This is a read-only display operation. Original HTML embeds a large settings string for unrelated calendar skins. The adapter retains only the exact published tile settings, empty calendar filters, visibility flags and shortcode4523 identity. It neither adds undocumented API parameters nor sends unrelated edit controls. The resulting actual encoded requests were1,269/1,268bytes and returned200 for December2026/January2027, respectively; response bodies were66,290/22,941bytes.

The observed January response uses **`Content-Type: text/html; charset=UTF-8`** for its JSON body. The bounded verification returned HTTP200 at the exact requested endpoint, without a redirect, for a1,268-byte form and22,941-byte response. Receipt: `/tmp/raleigh-primary-probes/artspace-render-content-type.json`; response SHA-256: `c1e22937834b0211ab9cc42f9f827f56268bc9c70112e550489e2776a7a79829`. The worker accepts this observed content type only within the independently validated Artspace display-form branch, alongside `application/json`; the adapter still requires the expected JSON structure and month identity.

`artspace_calendar_form(year, month, atts, window_start)` constructs only that exact form dictionary and rejects months outside the snapshot's60local dates. `valid_artspace_calendar_form(form)` independently validates exact keys/values, the current60-day month set (four-hour checkpoint boundary allowed), fixed action/flags and encoded body below8KB. The worker fixes the destination host/URL/Accept and must validate again at its internal transport boundary. There is no caller-controlled URL and no generic POST allowance.

Each monthly response binds `current_month.id/year/month` to the request. Tile count reaching80 or a visible load-more control fails completeness rather than publishing a truncated month. All three intersecting months are read. Date-only JSON-LD provides dates, not midnight showtimes; the explicit tile clock supplies each occurrence's time. Multi-day entries without per-session dates/clocks are held.

The page advertises the public WordPress `mec-events` type. Each native event ID is hydrated at:

`https://artspacenc.org/wp-json/wp/v2/mec-events/{id}`

This supplies the canonical first-party `/events/.../` URL and complete rendered narrative. The narrative must agree with the native tile JSON-LD after whitespace normalization. No ticketing hosts are fetched. Native external ticket URLs remain part of the publisher's prose where present.

Reviewed venue street: **201 E Davie St, Raleigh, NC27601**, from Artspace's primary footer. Onsite Artspace calendar programs use that exact street; member-only Jobe House/offsite entries are excluded or held. No coordinates are synthesized.

Accepted16 occurrences all have native images. Six holds are the members-only critique, Thanksgiving/Christmas/New-Year closures, the all-day teaching-artist application deadline, and the two-part Pottery+Plants date range whose individual session clocks are not supplied. Longest retained narrative:1,323characters.

## Raleigh Little Theatre: explicit show schedules

Robots/calendar returned200. Robots requires **Crawl-delay:10**, which the injected worker transport must honor. The complete index contains216 current/historical entries. The parser filters native displayed production date ranges before detail hydration; it never uses post dates as performance dates.

Three overlapping primary pages:

- https://raleighlittletheatre.org/shows/knock-knock/
- https://raleighlittletheatre.org/shows/cinderella-42/
- https://raleighlittletheatre.org/events/storytime-with-cinderella-2/

The publisher confirms **301 Pogue Street, Raleigh, NC27607**. Named Gaddy-Goodwin Teaching Theatre and Cantey V. Sutton Theatre are retained; no external ticketing portal is needed.

Knock Knock yields32 performances from explicit Wednesday–Sunday clocks, excluding November25/26 and replacing November21's morning schedule with the two published afternoon performances. Cinderella yields15 performances from explicit Friday/Saturday/Sunday clocks. Accessibility annotations describe existing performances and do not duplicate them. Storytime supplies exactly two dates and4–5PM intervals, not a continuous December12–19event. Approximate runtimes never become invented end times.

Descriptions retain the complete show narrative, ticket information, cast and accessibility section, while excluding unrelated promos/navigation. All49 performances have the publisher's header image. Longest retained narrative:2,042characters.

## Disabled or unresolved discovery results

| Candidate | Primary page or feed | Evidence / disposition |
| --- | --- | --- |
| Theatre Raleigh | https://www.theatreraleigh.com/events | Wix page200 but only production ranges. Linked authoritative ticket calendar's https://theatreraleigh.ludus.com/robots.txt returned403; stopped before calendar fetch. Keepdisabled. |
| Craft Habit | https://www.crafthabitraleigh.com/classes--events-calendar.htm | Canonical host robots403; stopped without page fetch. Keepdisabled. |
| Marbles | https://www.marbleskidsmuseum.org/ | Canonical host robots403; stopped without calendar fetch. Keepdisabled. |
| LGBT Center of Raleigh | https://www.lgbtcenterofraleigh.com/calendar | Page200 embeds Google Calendar. Google calendar robots permits only `/` and disallows other paths; public ICS is robots-disallowed and was not fetched. Keepdisabled. |
| ShopSpace | https://www.shopspace.org/classes | Robots/page200; calendar is Bookeo widget account41561HAT76A15B81BB2668. Public feed contract unresolved; no speculative endpoint or partial ingestion. |

Identified but not fetched LGBT public feed:

`https://calendar.google.com/calendar/ical/c_vtvh7m2dboea308penr1fs41nk%40group.calendar.google.com/public/basic.ics`

Existing healthy NCMA, NC State Localist, and DNCR Localist sources remain separate and unchanged. Gregg Museum's existing paused ICS was not duplicated or enabled.

## Verification and temporary evidence

`tests/test_raleigh_direct_arts.py` uses only synthetic fixtures. Its15 targeted tests cover exact source/URL binding, all60local dates/year boundary, native UTC/local agreement, full descriptions above2,000characters, fail-on-overflow, exact streets, complete pagination and both Cary sources, checkpoint integrity/expiry, deadline reserve, theatre recurrence/exceptions, Artspace date-only safeguards, month overflow, and independently bounded renderer forms.

Four full offline replays use temporary publisher captures under `/tmp/raleigh-primary-probes/`. Full publisher narratives are not committed to this repository. Complete result files are `/tmp/{source_key}-arts-replay.json`; each includes all normalized events and its final checkpoint. Approximate checkpoint JSON sizes are455KB Natural Sciences,181KB Cary,149KB theatre,56KB Artspace, all below850KB. These artifacts are the expected description/address basis for production reconciliation, not evidence that production has already ingested anything.

## Additional completed discovery: Tin Roof and Fortnight

### Tin Roof Raleigh — implemented in a separate collector

`roomquest/raleigh_direct_additional.py` implements `tin_roof_raleigh_nc`, exact tuple `https://tinroofraleigh.com/calendar/`, `html/html`, `America/New_York`. The calendar is a published Gigwell widget, not the six generic promotional cards in server-rendered HTML.

The native markup binds agency315647, identity315632, preset`b8txja`. Its public scripts are https://connect.gigwell.com/gigstream/gigstream.js and https://connect.gigwell.com/gigstream/app.js. Both connect.gigwell.com and api.gigwell.com robots returned200 and allow these reads. The scripts publish the settings GET at https://api.gigwell.com/api/agency/315632/booknow/presets/gigstreamSettings and the calendar GET at https://api.gigwell.com/api/gigs. The selected settings explicitly enable description display and define a2-month range, limit1000 and ascending date order.

The calendar query uses only its published `startDate`, `endDate`, `artists`, `venues`, `agencies`, `limit`, and `direction` arguments. It narrows the request to the frozen60local dates, agency315647, unchanged empty artist/venue filters and limit1000. API returned200/85,601bytes, with `hits=82` and82unique results. Two rows precede the window in Raleigh local time; all80remaining rows have complete native narratives. No sampling/pagination truncation is accepted: reported hits must equal returned count, under the collector's200manifest cap.

All rows independently bind venue315647, Raleigh, NC27603, US, and America/New_York. Three supply the street directly; the official Tin Roof footer supplies the same **300 Glenwood Ave, Raleigh, NC27603**. This exact venue mapping is used when the API omits its street; conflicting city/state/ZIP/street is held. No coordinates are inferred. Native artist-profile images are displayed by this public widget and are retained only when a row's artist ID matches its returned profile on the reviewed Gigwell resource host/path.

The row's `startDateTime` is the exact clock displayed by the native calendar and agrees with `localDate` in Raleigh. It coincides with `doorOpenDateTime` in this capture. Individual performance/end clocks are absent; no end is inferred from the separate duration field. Event URLs remain the actual canonical calendar page, while native IDs keep simultaneous entries distinct. No invented detail links or query parameters are added.

All3 public GET steps complete before stage output. Checkpoints use the same `arts_v1` completeness shape: `listing_complete=true`, `pending_pages=[]`, queue length/count/cursor equality, plus `checkpoint_complete(state)` for the shared wrapper. Caps are200manifest/500events/850KB/12,000description characters. Current replay80events,2outside-window holds,80images, longest native narrative442characters, approximately139KB checkpoint. The7 synthetic tests in `tests/test_raleigh_direct_additional.py` cover complete-only boundaries, exact identities, total/count agreement, long prose, native timezone/date/street consistency, checkpoint tampering and separate native IDs.

Temporary result: `/tmp/tin_roof_raleigh_nc-additional-replay.json`. This brings the two implemented modules to **313 accepted occurrences** in their captured windows (233arts/community plus80TinRoof). Production access is still separately verified by the normal worker.

### Fortnight Brewing — accessible, but narrative quality hold

Primary https://www.fortnightbrewing.com/event-calendar/ and robots return200. The page labels two independent R34ICS containers as Cary and Wake Forest. Its exact public JavaScript at https://www.fortnightbrewing.com/wp-content/plugins/ics-calendar/assets/script.min.js?ver=12.1.3.2 describes the display-only `action=r34ics_ajax`, `subaction=display_calendar` POST to the same host's `/wp-admin/admin-ajax.php`, using each native public argument token/nonce. Both exact display reads returned200, with503,364/361,868bytes. No blocked paths were requested.

Each response contains a complete15-month grid, August2026–October2027:603Cary and265WakeForest rows overall,90+39within the60-day window. Public programs have title/time only. Cary's9description blocks contain only runner emoji; WakeForest's repeated Music Bingo hover blocks contain its street only. The remaining attachment belongs to a private party and was not followed. There is no complete public-event narrative to retain for these129rows.

Keep `fortnight_brewing_nc` pending/disabled at its exact calendar URL with reason `publisher_event_narrative_unavailable`. The primary streets are1006SWMaynardRd,Cary,NC27511 and1894SFranklinSt,WakeForest,NC27587, but a correct street does not supply the missing event description. No adapter/transport extension is enabled for this lead. Evidence inventory for both additional leads: `/tmp/raleigh-primary-additional.json`.
