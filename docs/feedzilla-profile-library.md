# Feedzilla calendar-recognition profiles — EVE-159 (November 23, 2026)

Research-backed guide. **No source is registered or published just because a fingerprint matches.** Use only an actual publisher-linked endpoint, the existing access/robots and rights rules, verified calendar scope, complete pagination and real dated event/venue evidence. The fingerprints below complement the current ICS, WordPress TEC, Localist, Squarespace, JSON-LD, ChamberMate/GrowthZone, Legistar, Socrata, Revize and OpenActive paths; they do not replace working collectors.

## Example collector profiles

| Profile | Recognizable evidence in a publisher page or response | Extraction / completeness contract | Support status |
|---|---|---|---|
| ICS | `BEGIN:VCALENDAR`, `VEVENT`, calendar-wide subscription URL | UID and recurrence instances; a one-off .ics download is not a recurring feed | Existing |
| WordPress TEC | Actual `/wp-json/tribe/events/v1/events` or `rest_route=/tribe/events/v1/events` response | `{"events":[{"id":42,"title":"...","start_date":"..."}],"total":1,"total_pages":1}`; `page` and `per_page` | Existing |
| Localist | Site `/api/2/events` envelope | `{"events":[...],"page":{...}}`; preserve time/venue and pagination; some operations require OAuth | Existing |
| Squarespace | Actual publisher events collection and validated `format=json` | Only the verified calendar collection, not arbitrary Squarespace JSON | Existing |
| Schema.org | `<script type="application/ld+json">` with `@type:Event` or Event microdata | `name`, `startDate`, `location.Place`, stable event URL, true occurrence identity; individual event pages alone are not feed evidence | Existing, strict |
| OpenActive RPDE | `{"items":[...],"next":"https://...","license":"..."}` | `next` is a cursor to checkpoint; **empty items do not terminate the feed**; record deletions | Existing specialized |
| CivicPlus | Publisher's `iCalendar.aspx` categories and actual category-specific links | Verify category-wide ICS; RSS from `rss.aspx` may be news or a short horizon | ICS existing |
| FullCalendar / Drupal | `new FullCalendar.Calendar(... { events: ... })` + publisher JSON source | Date-bounded `start`/`end` requests; verify the publisher-linked source and any page/window limit | **Signal only** |
| Spektrix | `system.spektrix.com/<client>/api/v3/events` or `/instances` in publisher-linked code | Separate Event (show) from Instance (dated performance); date-bounded public instance reads | **Signal only** |
| Elfsight | `elfsightcdn.com/platform.js` plus `elfsight-app-...` | Widget does **not** demonstrate a documented public calendar feed; never infer widget backend URL | **Signal only** |
| Communico | Library events page with an enabled RSS button | Publisher-enabled event RSS, not generic news; verify all filtered locations and dates | Candidate research |
| Ticket Tailor | Publisher box office widget or published ticket listing | `GET /v1/events` requires a box-office API key (Basic Auth); use only publisher-permitted integration | Permission-backed |
| Eventbrite | Publisher event page or widget | REST v3 requires private token/OAuth; link is not a feed | Permission-backed |
| Wix Events | Wix Events site/widget | Wix Events V3 query requires identity/permissions; don't assume public API | Research |

**Example desired future profile data (illustrative only, not a deployed config):**
```json
{"family":"spektrix","fingerprints":["publisher-linked Spektrix API v3"],
 "mode":"detect_only","event_id":"event ID","occurrence_id":"instance ID",
 "paging":"bounded date windows","admission":"existing verified Feedzilla registration"}
```

The current first-pass `calendar_profile_signals.py` implements *only* bounded, two-evidence recognition of Spektrix, FullCalendar and Elfsight when the existing HTML classifier would otherwise return `no_reusable_calendar`. It emits specific technical hold reasons with the **same deferred retry**; it performs **no outbound fetch**, adapter activation or registration. Real fixture-based and official-API adapters remain subsequent batches. Verified first-party feeds always take priority.

## Primary official references

- TEC REST pagination: https://docs.nexcess.com/software/the-events-calendar/event-tickets-rest-api/
- Localist API: https://developer.localist.com/doc/api
- Schema.org event structure: https://developers.google.com/search/docs/appearance/structured-data/event
- OpenActive RPDE `next` semantics: https://openactive.io/realtime-paged-data-exchange/
- CivicPlus actual iCalendar selection: https://cp-civicimpactplatform.civicplus.com/iCalendar.aspx
- FullCalendar publisher JSON feed: https://fullcalendar.io/docs/events-json-feed
- Drupal REST Export feed: https://www.drupal.org/docs/extending-drupal/contributed-modules/contributed-module-documentation/fullcalendar-block/how-to-use-a-drupal-view-as-the-event-feed-source-of-fullcalendar-block
- Spektrix public API and instances: https://integrate.spektrix.com/docs/API3 and https://integrate.spektrix.com/docs/apieventfiltering
- Communico RSS events: https://communicocollege.com/rss-event-feeds
- Elfsight public embed: https://help.elfsight.com/article/1248-how-to-dynamically-change-the-event-calendar-layout
- Ticket Tailor API authentication: https://developers.tickettailor.com/docs/api/get-all-events/
- Eventbrite API authorization: https://www.eventbrite.com/platform/new/api
- Wix Events APIs: https://dev.wix.com/docs/api-reference/business-solutions/events/event-management/events-v3

## London original-receipt suite

1217 Poplar Union pagination limit; 1219 Horniman / 1226 The Albany pagination needed. 1218 Oxford House, 1223 Spitalfields Music, 1225 South London Gallery Event JSON-LD missing. 1220 Conway Hall identity conflict. 1221 Rich Mix, 1222 Omnibus Theatre, 1224 Museum of the Home no reusable calendar. These ten original IDs were processed but had **no registered source IDs or published events** in the Nov 23 readback. Recheck the same IDs only after the corresponding generic capability is deployed and the existing Admin technical-recheck gate permits it. Never resubmit duplicates to imply success.

**Next work:** extend complete calendar discovery (publisher-linked ICS/API/embedded feed), durable multi-run pagination and evidence-backed event extraction; add a candidate-scoped diagnostic API and broaden gated recheck for the existing IDs. Distinguish submitted, recognized, registered, staged, published.
