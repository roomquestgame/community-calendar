# Held feed-registration audit, batch 1 of 10 — 2026-11-23

## Scope and source of truth

User-approved finite ten-receipt repair batch. Read-only production baseline: `rq_curator_private.feed_registrations` in EventQuest Supabase; public publisher pages separately inspected. The **84** `status=review` registrations and **73** predicate-eligible rechecks belong to this private registration queue, **not** the separate `municipal_event_sources.approval=pending` count. All 10 selected receipts were still `review`, unlinked and predicate-eligible on the latest readback. No queue, source, category, event or approval record was edited during this audit.

Normal user-signed Admin rechecks: `https://eventquest.ai/admin/data/tools?section=registration`, **Recheck existing registrations from CSV** with `registration_id,url,note` and a deployed-fix verification note. Rechecks must preserve the original ID and submitted URL. The analyst's connected browser does **not** have a confirmed signed-in EventQuest Admin session. **0 Admin rechecks submitted**.

## Individual evidence and next disposition

| Registration | Publisher and observed facts | Correct disposition |
| --- | --- | --- |
| **77** | Motorco Music Hall, Durham; original homepage points to `https://motorcomusic.com/calendar/`. Original upstream `scrapers/motorco.py` recognizes inline FullCalendar data, but that script is not an automatically registered shared feed. The public calendar page's extracted text did not expose an event list. | Keep review until a **validated reusable FullCalendar collector** proves complete real future events, times and venue; do not assume the legacy scraper's fabricated end is authoritative. |
| **79** | Lincoln Theatre, Raleigh; `https://lincolntheatre.com/events/` shows individually dated shows and links. The tested guessed TEC endpoint was 404. | Recheck after suitable bounded HTML adapter; preserve age restrictions, dates and cancellation/price evidence; never treat partial 20-detail prefixes as complete. |
| **91** | City Lights Books, San Francisco; `https://citylights.com/events/` has dated author sessions and detail URLs. Some are virtual or at separate offsite venues. Guessed TEC endpoint returned 404. | A multi-event native/HTML collector must check venue/mode per occurrence, not use the bookstore as a blanket point. |
| **129** | Duke Arts Coffeehouse lead points to `https://arts.duke.edu/events/`, a broad university-wide calendar mixing other locations. The old `scrapers/duke_arts.py` does not preserve actual campus venues and assumes generic duration. | **Do not** promote the broad university listing under the Coffeehouse source identity; require explicit venue-scoped evidence. |
| **226** | Lynchburg Regional Business Alliance, `https://business.lynchburgregion.org/events`, exposes multiple same-host `/events/details/<slug>-<id>` entries. Separate native `https://business.lynchburgregion.org/api/events` returned event IDs, timed occurrences and venues. | Add generic **GrowthZone** detection from the real unfiltered collection page, probe native `ArrayOfEventDisplay` with existing provider, require timezone profile. Code on this branch; not deployed; no Admin recheck yet. |
| **328** | Pabst Theater Group, Milwaukee; many show details across six named venues, with cancellations and date ranges on `https://www.pabsttheatergroup.com/events`. Guessed `/calendar.ics` returned 404. | Need complete provider/venue-safe pagination and per-show occurrence validation, not a partial scrape. |
| **331** | Cambridge Wine School, `https://localwineschool.com/cambridge/events/wine-tastings-and-courses/` shows **52 listings** over multiple venues and local UK times. | Keep review until a sufficiently bounded multi-page collection with each event's own venue/time and original booking/price evidence. |
| **441** | Friends of FDR Park, Philadelphia; `https://www.fdrparkphilly.org/events` prominently embeds a Google calendar. Site's `?format=json` responds with Squarespace metadata, but this does **not** by itself prove an Event collection. | Recognize embedded-calendar or verified machine feed only after a real full upcoming event snapshot and scope check. |
| **561** | Las Vegas–Clark County Library District East Las Vegas: submitted ICS URL has corrupted base64 `data=` query. An equivalent valid **approved collecting source #3228** has 297 future preview events and venue count 297. | **Reuse existing #3228**, do not retry invalid URL or register a replacement. Auto-registration should validate encoded filters and offer existing-source match/superseded receipt via Admin. Receipt #561 itself remains in review. |
| **878** | Sustainable Oakington and Westwick: original Nov 6 article is one announcement; the same publisher is already **approved/collecting as source #6212** at official full `https://sustainableow.co.uk/feed/`, with one future staged event on readback. | **Reuse existing #6212**, no duplicate article-source; the original receipt #878 still reads review and is not automatically closed. |

No confirmed new registrations, new public event publication, source approvals, Admin rechecks, or production Vercel deployment from this audit.

## Reusable automation change on this branch

`roomquest/feed_registration.py` uses `growthzone_calendar_candidate(url,body)` to recognize a possible native GrowthZone calendar only when the **original unfiltered** same-publisher `/events` page identifies itself as an Events Calendar and links **at least two distinct** same-host `/events/details/<slug>-<id>` occurrences. Candidate `/api/events` is then fetched via the same robots-aware, deadline-bound native collector path; the source can be `discovered` only after `ArrayOfEventDisplay` identification, verified public event payload, the existing native collector's successfully parsed record(s), and a real configured timezone profile. The original source identity and URL remain authoritative for handoff; no inferred venue, coordinates, timezone, publisher rights or event acceptance is added. A denied or unverified candidate retains the original review outcome.

`tests/test_growthzone_calendar_registration.py` supplies synthetic positive/scope/timeout/robots/timezone negatives. **Tests authored but not executed in this connector-only session**; collector's standard focused local run remains a review requirement. No routine GitHub CI workflow or label should be dispatched.

## Acceptance and follow-up

1. Review the GrowthZone detector against an actual captured *HTML* and *raw XML* response, and run focused local tests, including existing provider registration/robots/identity tests. No new global test workflow.
2. Deploy after reviewed PR/merge through ordinary collector Vercel process and verify the **actual matching SHA**.
3. Add the approved publisher's real IANA timezone via the existing source-profile/Admin route (profile registry was empty at audit); if the normal Admin UI cannot configure it, record a genuine Admin capability gap rather than writing direct SQL.
4. Submit the eligible original **#226** through the signed-in Admin recheck CSV only *after* verified deployment and profile support; verify source receipt, full staging, rights/venue decisions, and unique Events/Map publication separately.
5. In subsequent cohesive batches, improve shared FullCalendar, structured HTML detail, Squarespace-embedded calendars and 20-detail completeness, with isolated near-miss tests. Add encoding/duplicate-source reconciliation so **#561** and **#878** are not recommended for retry. No robots/access bypass or bypassing Admin registration.

Related: EventQuest Linear EVE-79 (expansion standard), EVE-10 (Admin source management), EVE-6 (unified provider ingestion).
