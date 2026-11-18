# EventQuest Batch 01 — Fairfax County / OC Parks Drupal source audit (2026-11-18)

This is a **real, read-only first-party canary** for candidates #9 and #10 of the owner-approved batch of ten. The earlier [Batch 01 manifest](public-source-canary-batch-01-20261118.json) and [review](public-source-canary-batch-01-20261118.md) retain the original publisher links and all hold dispositions. No source registrations or events were changed.

## Fairfax County Events, Virginia
- Official URL: https://www.fairfaxcounty.gov/events/ (HTTP 200; publisher robots permits public path).
- Embedded Drupal `drupalSettings.fullCalendarView` returned **311 rows**, with `title,id,url,start,end,fulldescription,eventtype,fulldescriptionimage`. **263** rows labeled Community Event; **40** Public Meeting; a few other types. **310** rows have nonempty publisher full-description markup, maximum observed 561 characters. No complete `venue_name`, event-owned address or coordinates in the event list.
- Source-specific detail sample: https://www.fairfaxcounty.gov/events/parks/huntley-meadows/poetry-nature-sketch-hike/010927 provides exact date, time and full narrative, but its **Directory Location** block is not a verified venue/address in the inspected HTML. Do not use the Government Center footer address or guess a park just from a URL prefix. Public meetings must be routed to EventQuest Civic, not misclassified as entertainment.
- Publisher alternative: https://www.fairfaxcounty.gov/calendar/RssFeed.aspx?cal=1 is an official 10-item **today-only** public-meeting RSS feed. It lacks explicit event dates and its dates cannot be invented from RSS `pubDate`; not a substitute for a full dated event feed.
- An external public Mapsee research catalog includes 25 park/venue mapping examples, but those **do not prove** any particular event's venue. Review each exact event against current official venue evidence before admission.

**Disposition:** HOLD; no full venue attribution and no completed source-scoped safe-collection contract. Public event narrative and images not approved for republishing in this audit.

## OC Parks, California
- Official URL: https://parks.oc.gov/events (HTTP 200; publisher robots permits public path).
- Embedded Drupal FullCalendar 5.x `fullCalendarView[0].calendar_options` contains an `events` array of exactly **500**, the configuration's apparent list cap. Example items have `id,eid,url,title,start,end`; the inspected event row's `des` was empty. Event-owning park/trail and full body require official detail-page resolution. A partial/capped 500-row response is never certified as a complete feed.
- Do not map all events to Orange County Park headquarters. Source map catalogs contain 17 street examples, not proof of exact event venues. Image permission is not verified by a URL.

**Disposition:** HOLD pending proven complete pagination/date-window coverage, source-owned detail descriptions, exact venue coordinates and permitted image handling.

## Operational boundary
- Both use source-specific Drupal versions and cannot safely share a generic “all events are fully described/geocoded” assumption.
- First-party page access proves transport, not publisher rights. Factual times and descriptions must be preserved only when actually supplied; unknowns remain held. Images fallback until source/media permissions pass.
- Existing Fairfax County Public Library ICS sources are separate publishers and are not duplicated.
- No production SQL, source registrations, event/venue records, PG17 squash files, collector jobs, category/overlay backfills, cron, native/client release or future-date estimates were changed.
- All ten Batch 01 sources now have explicit dispositions; held items remain held. The next batch is **a new group of at most ten**, using verified source identities before any enrollment.
