# Remaining Boston museums, family programs and seasonal market evidence

Native calendars captured on 14 November 2026. This batch adds four exact profiles and repairs the existing empty Public Library of Brookline source (id 3718). Already published baseline sources are excluded.

| Source | Captured rows | Full description characters | Complete street locations | Checkpoint bytes |
|---|---:|---:|---:|---:|
| [Museum of Fine Arts, Boston](https://www.mfa.org/programs) | 317 | 90–8351 | 1 | 403965 |
| [Institute of Contemporary Art/Boston](https://www.icaboston.org/calendar/) | 48 | 499–3326 | 1 | 113086 |
| [Boston Center for the Arts](https://bostonarts.org/experiences/) | 4 | 1425–2850 | 2 | 12574 |
| [SoWa Christmas Market](https://www.sowaboston.com/sowa-christmas-market/) | 31 | 3007–3007 | 1 | Not needed |
| [Public Library of Brookline](https://brooklinelibrary.libcal.com/ical_subscribe.php?cid=20102) | 189 | 27–1697 | 4 | Not needed |

## Completeness and identity

MFA traverses all 20 native program-calendar pages before hydrating the 328 selected occurrences. Each detail must match its exact native performance id, title, timezone and add-to-calendar date/time. It preserves both the selected session theme and the complete generic narrative. Eleven already-ended November 14 occurrences are excluded, leaving 317 within the rolling 60-day window. The largest captured description is 8,351 characters. The source alone receives the reviewed 500-manifest/500-event checkpoint exception; its complete checkpoint remains below 900,000 bytes.

MFA's exact venue point (42.339381, -71.094048) comes from the explicit `Museum.geo` object on its Google Arts & Culture partner profile, which names the same museum and full 465 Huntington Avenue address. Massachusetts Historical Commission/MassGIS record BOS.7493 independently confirms the named museum building and address with a nearby building point. The selected point is a venue marker, not a map viewport. Both coordinates and provenance are pinned in resumed checkpoints. All 317 native narrative hashes remain unchanged after adding this verified point.

ICA uses full HTML event narratives rather than truncated JSON-LD descriptions. Its permitted native per-event ICS exports supply all explicit occurrences; ICS and visible HTML date counts must agree. Twenty-one physical public series yield 48 current events. Virtual, member-only and out-of-window series are excluded. A stable post-id plus occurrence-start identity survives upstream ICS index changes.

BCA loads all eight native cards, including those initially hidden by its client-side “Load More” display. Its four verified timed public programs retain complete biographies and descriptions plus their explicit 539/551 Tremont Street addresses. Date-only exhibitions and ambiguous schedule ranges remain held.

Brookline reuses its existing LibCal ICS URL and source key. All 189 eligible records retain the complete native descriptions and resolve exact published room names to the three official branch streets. Four offsite English classes explicitly name United Parish Church at 210 Harvard Street; the church confirms the Brookline postal address and Marion Street entrance. Four genuinely empty descriptions remain held after checking their empty native detail bodies. Staff-use, closed, virtual and cancelled items are excluded. The native 500-item export reaches beyond the complete 60-day window; the parser fails closed if that boundary no longer covers the window.

SoWa Christmas Market is a distinct seasonal profile from the existing First Friday source. It expands only the publisher’s explicit November 20–December 27, 2026 dates and month-specific hours. Thirty-one daily occurrences use the native FAQ venue at 550 Harrison Avenue, not the separate office address. Every daily opening and closing was compared against an independent literal date table. Monday closures, Thanksgiving, Christmas, Black Friday hours and Christmas Eve hours all match. No 2027 schedule is projected. The complete 3,007-character program and all current visitor FAQs are retained; hidden legacy festival text is excluded.

## Verification and transport

Twelve focused tests pass. All five profiles were replayed through the actual integrated `_process_claimed_source_with_pacing` path, replacing only HTTP and RPC side effects. The root record/checkpoint validators accepted every result. All 589 descriptions and street addresses match their captured records exactly; incomplete checkpoints staged zero rows. MFA requires 53 checkpoint writes, ICA seven and BCA five. Hydration caps of 10/4/2 details retain the existing monotonic deadline, 12-second reserve and guarded publisher pacing. BCA’s 10-second crawl delay remains in effect.

These captures and replay results establish parser and pipeline behavior, not production access. During the first batch rollout the ordinary production guarded transport returned `publisher_http_403` for all four bookstore feeds: Brookline Booksmith, Harvard Book Store, Porter Square Books and Trident. They were paused for review. No alternate host or access route was tried. Production verification of this second batch is recorded by the batch owner.

## Remaining publisher holds

- **ShowUp:** No future native events; newest visible event November 6, 2026. Existing paused identity retained. Squarespace JSON export disallowed by robots; no export bypass.
- **USS Constitution Museum:** Ordinary calendar HTTP 403 after allowed robots check; no alternate access route attempted.
- **Boston Children’s Museum:** Ordinary calendar HTTP 403; access hold.
- **Brattle Theatre:** Ordinary calendar HTTP 403; access hold.
- **Boston Art Book Fair:** Robots request returned HTTP 429; no publisher content fetched. BCA gives date range without confirmed hours; no inferred clock.
- **Brookline Library:** Native ICS descriptions blank. Each permitted event detail returned HTTP 200 but its #s-lc-event-desc was also empty; these four records remain held.
- **Boston Center for the Arts:** Four date-range-only or ambiguous-clock cards held; exact URLs in source checkpoint diagnostics. Two exhibitions lack timed occurrence schedules; Art Book Fair has no native hours; The Head Is Not the Star of the Body body refers to a past November 10 performance despite a November 10–15 header.

The adjacent JSON contains all exact source tuples, complete street sets, description hashes, raw capture paths, checkpoint byte sizes, all 31 SoWa date checks and integrated worker replay receipts.
