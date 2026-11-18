# Batch 01 execution: Mountain Home first-party HTML pilot (2026-11-18)

This is the **actual read-only event ingest canary** for source #8 of the [ten-source cohort](public-source-canary-batch-01-20261118.md). Other nine remain held or under investigation. Publisher hosts: [official calendar](https://enjoymountainhome.com/events/), [official print details](https://enjoymountainhome.com/events/print-events/).

## Live publisher evidence (no production writes)

- Independent isolated HTTPS GETs succeeded for `/events/` (186,486 bytes), `/events/print-events/` (56,179 bytes), `/robots.txt` (explicit `User-agent: *` with blank `Disallow:` and separate `/cgi-bin/` exclusion), and a detailed publisher event page.
- There were **35 dated event links in the calendar listing**, and **114 date/title narrative entries in the public print view**. The longest observed print narrative had **1,309** characters, one was empty. More than 30 listing cards lack a complete event-specific time, numbered street, or uniquely matching print description, and are intentionally withheld. No claimed complete local coverage.
- A source-scoped parser validates **two exact URLs only**; it never follows arbitrary links, uses registration credentials, crawls event-detail pages or fabricates event durations/addresses. An explicit date tile must match the calendar URL, a parseable 12-hour clock must be present, and a Mountain Home event-owned numbered street must exist. Exact (date,title) match must appear in original print text. Unverified rows are not emitted.
- Source uses `America/Chicago`. The shared preview normalizer's UTC conversions were run with its **actual** `mapsee_adapter.record` and returned **4** event candidates. No image URLs were invented or approved; all use the image-fallback path pending rights/byte checks.

| Event title | Publisher date and local start | Publisher street | Full description | Venue status |
| --- | --- | --- | --- | --- |
| [A Sherlock Carol — Nov 20](https://enjoymountainhome.com/events/20261120-a-sherlock-carol/) | Nov 20, 2026 7:00 p.m. CST | 600 West 6th Street, Mountain Home, AR | 416 characters | held `missing_verified_venue_geo` |
| [A Sherlock Carol — Nov 21](https://enjoymountainhome.com/events/20261121-a-sherlock-carol/) | Nov 21, 2026 7:00 p.m. CST | 600 West 6th Street, Mountain Home, AR | 416 characters | held `missing_verified_venue_geo` |
| [A Sherlock Carol — Nov 22](https://enjoymountainhome.com/events/20261122-a-sherlock-carol/) | Nov 22, 2026 2:00 p.m. CST | 600 West 6th Street, Mountain Home, AR | 416 characters | held `missing_verified_venue_geo` |
| [Mountain Home Symphony](https://enjoymountainhome.com/events/20261122-mountain-home-symphony-concert/) | Nov 22, 2026 2:30 p.m. CST | 1600 S College St, Mountain Home, AR 72653 | 583 characters | held `missing_verified_venue_geo` |

**Accurate field contract:** `title`, `starts_at` in UTC on actual preview output, distinct publisher `event_url`/identity per occurrence, `venue_address` from that event, nonempty exact publisher-derived `description`; `lat`, `lng`, `image_url` are null, with `reason=missing_verified_venue_geo`. End time remains unspecified, leaving global start+three-hour unknown-end behavior intact.

## Tests and integration

The source module is `roomquest/mountain_home_chamber.py`; the existing `preview_worker.py` HTML dispatch calls it only for **`mountain_home_chamber_calendar_ar`**, with a 30-second budget and existing safe HTTPS/robots/allowed-host checking. Reuses existing event staging, geocoding, classifier and image-fallback semantics. No new cron, separate worker, platform, background scan, geocoder or source registry.

**Actual isolated test execution:**
```
python3 -m unittest discover -s tests -p test_mountain_home_chamber.py -v
# 8 tests passed
```
Live publisher-list plus public print data parse (real, unpatched parser; `mapsee_adapter.record` return normalizer): **4 candidate rows**, all correct UTC starts, full 416/583-character source descriptions and event-owned streets; all 4 **on venue-geo hold**, 0 publisher image URLs.

## Publication blockers and release sequence

1. Verify the publisher's allowable use beyond public robots access and preserve attribution. Event text/images have separate reuse rights; no image is licensed by this canary.
2. Obtain reviewed Geocodio/address results for the exact two event-owned streets using the existing bounded geocoder. No publisher HQ, source coverage centroid or guessed pin.
3. Check new source's `community_source_supported`, `publisher_event_provider`, `publisher_event_extractor`, media-stage and `record_preview_v3` admission contracts before adding a **forward-only** production migration. The current private `record_preview_v3` requires exact staged media evidence even for the fallback case; a nonregistered source or stale photo stage must not claim success.
4. On authorized release, register the exact reviewed source with existing demand, rights/review, geocoder/coverage-seed/queue controls, then confirm staged-vs-public counts, categories, time, venue geo, image fallback, Home/Events/Map visible results and duplicates against real production state.

No source row, production event, image, database migration or live worker was changed in this PR. In particular, the PG17 squash baseline and active unified classification/backfill jobs remain intact. This is **one canary parser passing its real publisher inputs**, not proof that Batch 01's ten publishers are all working or that the four events are visible in EventQuest.
