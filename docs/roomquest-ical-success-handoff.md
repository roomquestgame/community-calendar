# iCal pacing before successful worker handoff

Generic sources with both `kind = 'ical'` and `platform_adapter = 'ical'`
now record their preview through `community_collector_record_preview_v2`.
The existing publisher-media `community_collector_record_preview_v3` route
keeps precedence, including reviewed ICS sources that already use it.

The v2 call includes the existing bounded publisher pacing fields:

- `p_publisher_crawl_delay_seconds`
- `p_publisher_retry_after_seconds`
- `p_publisher_wait_unbounded`

Successful completion is recorded only after every staging batch has been
accepted. Valid empty feeds use the same recording contract. Collection or
staging failures record their error and captured pacing through v2; a failed
record RPC remains a worker failure and never falls back to the legacy RPC.
Unbounded publisher waits continue to require review before staging.

## Collection completion and publication review

An iCal source can finish collection successfully while its events remain on
the existing `venue_location_unresolved` review hold. After `action = 'collect'`
returns an explicitly successful recorded result (`complete = 1`, `failed = 0`),
a publication result of `idle` now finishes that collector ticket as `complete`.
The response still reports `publication.outcome = 'idle'`. This releases the
collector for unrelated sources without publishing unverified venues or
changing any source or event review hold.

An actual publication result of `busy` retains its cooldown. Failed collection,
recording or publication exceptions, publication-only continuations, and other
categories keep their existing finish behavior. The backend independently
requires a fresh successful pacing receipt before allowing the faster handoff.

## Deploy the backend first

RoomQuest backend migration **20261108041058** must deploy before this
collector. It widens v2 to accept exact `ical`/`ical` sources and records a
successful pacing completion marker in `collection_pacing_checked_at`, matched
to `preview_checked_at`. The backend uses that fresh recorded success when
deciding whether to end the two-minute slot cooldown early. Failed or busy
outcomes keep their cooldown. The previous collector remains compatible with
the widened backend and retains its existing cooldown.

This collector change leaves the configuration at **two iCal slots**. It does
not change network or robots checks, per-publisher waits, parser or recurrence
limits, invocation deadlines, the 20-event staging batch bound, the 10-event
publication bound, or venue review requirements. In particular, it does not
grant a worker permission to bypass a publisher's durable wait.

## Local verification

The focused suite plus WordPress regressions passed **410 tests and 35
subtests** in an isolated integration checkout of main
`2c8cc296713012a4a376fb0a259124a86925aace` with these changes applied;
`git diff --check` was clean. Tests cover successful and empty ICS collection,
completion after all bounded batches, partial staging failure, Retry-After and
fractional crawl delay, unbounded waits, recording failure, isolated pacing
state, and existing v3 precedence. They also distinguish idle publication from
capacity busy after collection and preserve continuation, other-category, and
failure outcomes. Existing robots, parser, transport, and worker tests pass.

```bash
python -m pytest -q tests/test_transient_staging.py tests/test_ics_family.py tests/test_holly_hill_pipeline.py tests/test_mecklenburg_sources.py tests/test_publisher_robots_cache.py tests/test_category_worker.py tests/test_category_entrypoint.py tests/test_roomquest_preview.py tests/test_roomquest_scoped_rpc.py tests/test_preview_transport_errors.py tests/test_wordpress_adapter.py
```

These are local fixture and mocked-transport results. They do not establish a
live deployment, a production queue drain rate, or a successful production
handoff. No live collection was claimed or triggered during this verification.
