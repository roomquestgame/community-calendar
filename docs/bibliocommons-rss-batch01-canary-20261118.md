# EventQuest Batch 01 — BiblioCommons RSS live canary (2026-11-18)

These are candidate sources **#1 King County Library, WA**, **#2 Central Rappahannock Regional Library, VA**, and **#3 Palm Beach County Library, FL** in the existing ten-source Batch 1 manifest. They are not approved for automatic registration or commercial republication.

## Publisher rights and exact sources

BiblioCommons [Terms of Use](https://carmel.bibliocommons.com/info/terms) acknowledge specifically permitted RSS/XML feed use as an exception to automated-harvesting restrictions, but separately limit Service Content copying and commercial republication absent other permission. A publicly responding feed is **not** a license for EventQuest to republish full descriptions or event images. Preserve source-event links and attribution; source-specific commercial use authorization remains unverified. Do not enable these sources until that review passes.

RSS tenant endpoints, not the proprietary JSON gateway:
- King County: https://gateway.bibliocommons.com/v2/libraries/kcls/rss/events
- Central Rappahannock: https://gateway.bibliocommons.com/v2/libraries/librarypoint/rss/events
- Palm Beach County: https://gateway.bibliocommons.com/v2/libraries/pbclibrary/rss/events

The public XML has exact stable event URLs, start/end UTC times, source-local dates/times, nested publisher-event location name/number/street/city/state/ZIP and publisher latitude/longitude, whole RSS description fields, independent category/audience labels, cancellation and virtual indicators. Some event cards carry image enclosures; none are approved photos.

## Actual bounded live results

HTTP **200** and XML RSS confirmed for all three publishers. Page=N advances exactly 25 entries. The gateway does **not** honor a proposed limit=100 override. Initial three-page per-library audit:

| Source | Entries / unique | Timed / all-day | Numbered street | Publisher coords | Blank descriptions | Image enclosures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| King County | 75 / 75 | 73 / 2 | 64 | 64 | 0 | 53 |
| Central Rappahannock | 75 / 75 | 56 / 19 | 72 | 72 | 0 | 8 |
| Palm Beach | 75 / 75 | 71 / 4 | 69 | 73 | 0 | 75 |

### Read-only bounded collection and final cancellation guard

The first parser pass, before cancellation handling was tightened, counted 230 timed physical Central Rappahannock records (14 pages / 9.15 s), 425 Palm Beach candidates (23 pages / 19.26 s), and exceeded the 500-event cap for King County (page 23). **Those exploratory Palm Beach numbers must not be presented as a successful final feed** because the publisher explicitly marks some events cancelled.

Final 2026-11-18 cancellation-safe parser results:

| Publisher | RSS pages | Time | Final status | New public cards |
| --- | ---: | ---: | --- | ---: |
| Central Rappahannock | 14 | 9.80 s | **230** fully parsed source-owned, timed physical candidates, including **230 original venue coordinates** | 0 |
| Palm Beach | 1 | 0.79 s | **HOLD — explicit publisher cancellation needs safe tombstone propagation** | 0 |
| King County | 1 | 0.89 s | **HOLD — cancellation propagation**, plus previously measured >500 volume | 0 |

A cancelled entry is now an **explicit error**, not a skipped row that could accidentally leave a stale live card behind. To unlock Palm Beach and King County, the existing backend must safely ingest source-specific cancellation tombstones while keeping source completion honest and bounded. King County also needs a durable pagination/window strategy; never silently increase its maximum or accept a truncated snapshot.

The Central Rappahannock count is an **eligible timed physical subset**, not full library coverage: publisher feeds also contain date-only/all-day, virtual, and non-mappable entries. Publisher RSS may promote older highlights out of order and does not supply a proven finite-window record total. The two-post-horizon-page limit is a bounded collector convention, not proof of total inventory.

## Description, venue, image and overlay contract

- Source RSS description content passes through the existing HTML-to-text normalizer. It preserves cleaned narrative up to **12,000 characters** and fails rather than truncating longer descriptions. Some raw three-page descriptions exceed **2,000 characters**, and the existing backend public-event description constraint needs independent alignment before activation. Exact RSS-to-original-web-detail parity is not established for every event.
- Times must agree between explicit UTC and source-local clock fields. Date-only/all-day events are held, not turned into arbitrary midnight starts. Unknown end remains unknown; cancelled and virtual rows do not acquire physical pins.
- Only the individual event's own structured street and source-provided point are used, not the library HQ or source coverage centroid. Unmatched streets remain unknown until the existing bounded geocoder/review resolves them.
- Publisher category and audience labels remain individually available to the existing single category/holiday/audience overlay system. No new classifier or invented category.
- Image enclosure URLs are **not** copied to cards or to image candidates. Separate image reachability/bytes/MIME/rights and event match would be required before approval; otherwise the existing default image fallback is correct.

## Implemented code and isolated tests

- roomquest/bibliocommons_rss.py — three exact tenant profiles, bounded RSS parser, duplicate/repeated-page and XML safety rules, source text and coordinates, no remote image.
- roomquest/preview_worker.py — source-scoped branch before generic library parsing, using existing bounded publisher HTTPS/robots and exact gateway-host allowlist. It does not publish itself.
- tests/test_bibliocommons_rss.py and tests/test_bibliocommons_rss_integration.py — source, dates, description, geo, XML/identity, volume limits and protected dispatch.

**56 tests passed** in the isolated Python runner, including 16 new parser tests, 2 protected-dispatch integration tests, and existing BiblioEvents and community-formats tests. No routine GitHub CI was triggered.

## Release boundary: closed

Do not register or approve any of these sources until publisher rights are established, explicit cancellation/tombstone propagation and pagination/all-day handling are reviewed, backend description/media and provider contracts are coordinated, and source-specific stage/publication canaries pass. No Supabase migrations, historical PG17 squash files, production source rows, event records, running category/overlay jobs, or native clients were changed.

The next work remains within the original **ten-source batch**, not another batch of ten.