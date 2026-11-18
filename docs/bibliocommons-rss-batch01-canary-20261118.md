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

The tested **full bounded candidate pull** used 21 upcoming days and the real shared EventQuest record normalizer, not generated example cards.

| Publisher | Pages | Runtime | Fully parsed timed physical candidates | Source coordinates | Accepted photos |
| --- | ---: | ---: | ---: | ---: | ---: |
| Central Rappahannock | 14 | 9.15 seconds | **230** | 230 | 0 |
| Palm Beach | 23 | 19.26 seconds | **425** | 425 | 0 |
| King County | 23 | 18.71 seconds | **HOLD — 500-record cap** | Not certified | 0 |

King County raised an explicit source-volume error, **not** an accepted partial import. Its density requires a separate durable continuation/window strategy without lifting global source limits or losing events.

The two successful counts represent **eligible timed physical records**, not the publisher's complete programmes. All-day, virtual and unlocatable records are not converted into fabricated timed physical events; they are outstanding coverage cases. Feeds can promote older listings out of order. The two-page post-horizon stop is a bounded collector convention, not proof of full publisher inventory beyond the window.

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

**55 tests passed** in the isolated Python runner, including 16 new parser tests, 2 protected-dispatch integration tests, and existing BiblioEvents and community-formats tests. No routine GitHub CI was triggered.

## Release boundary: closed

Do not register or approve any of these sources until publisher rights are established, pagination/all-day handling is assessed, backend description/media and provider contracts are coordinated, and source-specific stage/publication canaries pass. No Supabase migrations, historical PG17 squash files, production source rows, event records, running category/overlay jobs, or native clients were changed.

The next work remains within the original **ten-source batch**, not another batch of ten.