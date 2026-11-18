# Batch 01 — OC Parks verified partial calendar (November 18, 2026)

The EventQuest owner explicitly approved **pulling the OC Parks events that can be verified** without waiting for complete coverage of the source's 500-entry Drupal calendar. This is a source-bounded, read-only **real publisher canary** with safe collector code, not a claim of 500 published events.

## Publisher origin and terms

- Official calendar: https://parks.oc.gov/events
- The source's `drupalSettings.fullCalendarView[0].calendar_options` contains **500** event-list records, with **234** dated on/after November 18, 2026. This is an apparent view cap; missing events cannot be inferred absent.
- Calendar list rows supply original `title,eid,url,start,end`, but no description. The collector fetches exact `https://parks.oc.gov/events/<slug>` publisher detail pages, never arbitrary event or registration links.
- Each verified detail page supplies its own dated schedule (`.info-date-time__body`), body (`#wysiwyg-body-node-na-0`) and street (`.info-location__body p.address`). Sample: [Oak Woodland Bird Walk](https://parks.oc.gov/events/oak-woodland-bird-walk-2) has a numbered street in Orange, CA. The original event page remains the card attribution link.
- The [Orange County Acceptable Use policy](https://www.ocgov.com/contact-county/acceptable-use) explicitly says website information is **generally in the public domain unless otherwise indicated** and cautions that third-party material and copyrighted photos may require separate permission. Therefore **do not extract, store, or republish site images in this pilot**, and keep source attribution. Verify exceptions before using any event image.

## Collector scope and live evidence

- Runs through the **existing** community HTML safe transport, source `oc_parks_verified_partial_ca`, timezone `America/Los_Angeles`. Maximum **32** selected upcoming publisher detail pages per refresh and **24** accepted event records, within a 21-day rolling horizon. At a 500-record source cap, this is deliberately **partial coverage**. Do not report it as total eligible events or the complete feed.
- Exact calendar start/end must equal exact event detail local date/time and DST abbreviation. Event IDs and links are source-validated. The detail title must agree with calendar title; incomplete body, unnumbered address or description over the current **2,000-character** writer limit is held rather than fabricated or truncated.
- Black Star Canyon Road **13333** is excluded: a public Mapsee/OC Parks location-note comparison documents it as a common Irvine Ranch administrative entrance/address, which is not the verified start point of each individual hike. Other unnamed/displaced staging areas never receive a county-centre pin.
- Direct reviewed source locations use **exact street + city + ZIP** matching against 12 OC Parks venue points preserved in public [Mapsee Drupal FullCalendar source research](https://github.com/tophe112-source/mapsee-aggregator/blob/main/drupal_fullcalendar_sources.json). These are first-party OC Parks location-node GPS entries, not automatically substituted for a changed event address. Unknown locations have null coordinates and remain for the existing geocoder/review.
- No new event image URLs or candidate URLs are emitted; no photo licensing/reuse or image download is implied. The ordinary placeholder is the only acceptable default.

**Live sandbox dry run** using the real publisher calendar and `roomquest.mapsee_adapter.record` on November 18:

| Observation | Result |
| --- | ---: |
| Calendar entries exposed | 500, source appears capped |
| Future-dated listing entries | 234 |
| Individual detail pages selected | 32 |
| Publisher HTTPS requests | 33 |
| Returned publisher-factual candidate rows | **12** |
| Full source narratives retained | 12 |
| Valid park coordinate rows | **8** |
| Valid streets with coordinates still unresolved | **4** |
| Explicitly cancelled active event cards | **0** |
| Publisher image links approved or imported | **0** |
| Production source registrations/events | **0** |

Actual bounded read: **20.4 seconds** for 33 publisher GETs. Observed event titles include *Introduction to Archery for Adults*, *Wild Tales*, and *Saturday Restoration: Habitat Adventure Trail*. The verified [official OC Parks calendar](https://parks.oc.gov/events) and [Oak Woodland Bird Walk detail page](https://parks.oc.gov/events/oak-woodland-bird-walk-2) are publisher references; no unverified event-detail URL is asserted here. Each original event URL remains bound to its own source row at collection time.

The initial dry run found **two publisher titles beginning with “CANCELED”**. The revised parser explicitly excludes canceled/postponed titles and also catches a detail page updated between list and fetch. A new registration must not be promoted to production **until there is an approved exact-source cancellation/tombstone propagation path** for cards that were published before the publisher cancels the event.

## Focused tests and release gate

- `roomquest/oc_parks_partial.py`: source-scoped 500 capped-list parser with 32-detail verified subset, exact event date/title, full description + original venue street, approved reviewed park points, and explicit no-image behavior.
- `roomquest/preview_worker.py`: only source key `oc_parks_verified_partial_ca` invokes it using the existing protected publisher transport; max 36-second budget. No extra worker, scheduler, geocoder, classifier, category overlay or source guessed by URL.
- `tests/test_oc_parks_partial.py`: 21 focused source assertions, including cancellation, false area-address prevention, time/address/details mismatches and no publisher image.
- `tests/test_oc_parks_partial_integration.py`: 2 exact-host/protected-dispatch tests.
- **68 focused + regression Python tests passed** in an isolated sandbox (these plus existing BiblioCommons, Mountain Home and community-format suites).

**Production release remains held** until verified status/cancellation handling, source registration/coverage/provider identity, publisher photo-stage fallback, actual database stage/readback and real public Events/Map cards are complete. The source can be added by a forward-only reviewed migration, not a reset of the PostgreSQL 17 baseline.

The owner approved a partial source, **not incomplete facts**. No active category/backfill job, PG17 historical migrations, source rights, other collectors, user-facing filters, or existing stored events were modified by this canary.
