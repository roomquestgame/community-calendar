# Boston detail-calendar continuation review

Eataly and Waverley Oaks had healthy incomplete checkpoints advancing at five follow-on requests per claim, with roughly two to two-and-a-half minutes between production claims. The collector now permits up to twelve follow-on requests for these two exact source keys. The seed listing remains a separate request, as before.

The change leaves the worker deadline, ten-second pre-fetch reserve, publisher pacing, guarded fetcher, full-description validation, record/body/checkpoint bounds, checkpoint schema and four-hour lifetime unchanged. Each request still checks the existing remaining-time condition. Night Shift and Trillium retain their five-request cap. No active checkpoint is discarded or rewritten by a migration for this change.

## Captured worker verification

The real category-worker entry point was replayed with official saved responses and mocked network/database boundaries. Every result was compared with the original native description hashes and exact identities, titles, dates, URLs, venue names, streets, cities and coordinates. Complete emitted rows also matched the old-cap replay byte-for-byte after canonical serialization.

| Source | Complete calendar claims, old → new | Actual production checkpoint remaining claims, old → new | Accepted / held |
|---|---:|---:|---:|
| Eataly Boston | 23 → 10 | 17 → 7 | 76 / 31 |
| Waverley Oaks Park | 10 → 4 | 4 → 2 | 46 / 0 |
| Night Shift | 1 → 1 | Unchanged source | 9 / 1 |
| Trillium | 1 → 1 | Unchanged source | 34 / 5 |

The production checkpoint replay used the read-only revision-six Eataly and Waverley snapshots observed after 23:59 UTC on November 14. All 59 already-hydrated rows survived unchanged. Their original start timestamps and schema remained intact, and previously fetched event details were not fetched again. This is a compatibility check with saved production state, not a production write.

All 165 accepted captured records retained their full native descriptions. No incomplete snapshot staged records or called publication. Each complete source called completed-preview and publication once. The replay simulated a 1.1-second per-request cost; it does not measure current publisher latency. Real network delays and pacing can produce shorter chunks through the existing deadline checks.

## Focused regression checks

`python -m pytest -q tests/test_boston_nightlife_remaining_continuation.py tests/test_boston_nightlife_remaining.py`

Result: **16 passed**. New checks cover unchanged full rows after a legacy checkpoint, exact source cap enforcement, an oversized caller-requested cap, eight-second publisher responses stopping after two detail requests within the actual worker window, checkpoint persistence before any staging, successful continuation, and unchanged supplied state when the reserve prevents progress. The existing source tests cover native narratives, clocks, declared recurrence, venue matching, path scope and tampered/expired checkpoints.

Machine-readable results: `boston-nightlife-remaining-continuation-20261115.json`. The ordinary robots redirect repair has separate evidence in `boston-nightlife-remaining-robots-repair-20261114.json` and is unaffected by this change.
