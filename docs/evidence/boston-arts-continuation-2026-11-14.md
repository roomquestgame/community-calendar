# Boston arts continuation efficiency — 2026-11-14

A production readback showed roughly 2–2.5 minutes between claims per source. MFA consumed one native listing page per claim and BPL consumed two pages, so complete snapshots took many scheduler cycles while using little of the existing fetch budget.

Only the two exact source profiles change their per-claim ceilings. MFA may fetch up to four consecutive listing pages in its existing listing phase and up to twenty event details in its detail phase. Boston Public Library may fetch up to six sorted gateway pages. ICA and BCA retain their four- and two-detail caps. Every loop still stops before initiating a request when the existing twelve-second reserve is reached. Shared worker scheduling, its maximum 36-second fetch budget, ordinary transport and publisher pacing are unchanged.

## Complete captured replay

| Profile | Publisher requests, before/after | Checkpoint writes and claims, before→after | Full eligible rows | Maximum checkpoint bytes |
|---|---:|---:|---:|---:|
| MFA |348/348|53→22|317|403,965|
| Boston Public Library |33/33|17→6|306|538,850|

Every identity, title, complete description, start/end date, event URL, venue name, street, locality, coordinates, timezone, attendance mode, location provenance and publisher category is identical to the original capture. Both variants stage zero rows before the whole snapshot is complete. BPL still accounts for all 3,259 unique native IDs across 33 pages.

The aggregate SHA256 of the full captured factual fields stays `4c258235d881f96bb8f9554d3a79fdd6ffa192a37c0f1bf939bac40e567e299b` for MFA and `614ef9798b42ad6b994df80b1893cc7ea171fc19c74839eecd853433aabbcc82` for BPL.

## In-flight compatibility and time bounds

Read-only production checkpoints captured at 23:55:36 UTC were replayed directly with the new collectors. MFA resumed its saved native page 4 (four listing pages already consumed), fetched 344 remaining URLs and completed in 21 claims. BPL resumed native page 9 (eight pages already consumed), fetched 25 remaining pages and completed in 5 claims. Both preserved the original `started_at`, window, record identities and full body/address hashes. No schema/version change or refresh/reset is required.

The replay calls the actual integrated `_process_claimed_source_with_pacing`, normal registry/record/checkpoint validators, and unchanged `pace_publisher` logic against captured HTTP responses. A fake clock advances for actual pacing waits and assumed response costs. At 0.25 seconds per response plus the ordinary one-second minimum publisher spacing, the longest MFA/BPL claims use 19.25/5.25 seconds. With slower 3-second responses, the deadline guard reduces MFA work per claim and still produces the same 317 records (46 claims); BPL remains 6 claims, with a longest18-second claim. These are controlled correctness/capacity checks, not measured production latency promises.

37 focused tests and52 subtests pass, including propagation of robots/403/pacing failures, twelve-second reserve stops before additional requests, legacy checkpoint resume, complete-only staging, exact-source capacities and the full description boundary. The existing four-hour checkpoint TTL, 900,000-byte cap and source-specific record/manifest limits remain unchanged.

## Artifacts

- Full replay results: `research/arts-remaining/continuation-worker-replay.json`.
- Read-only live checkpoint capture: `research/arts-remaining/production-inflight-before-continuation.json`.
- Reproducible replay script: `research/replay_arts_continuation.py`.
- Existing primary data captures and all street/description evidence remain in the earlier Boston arts evidence files.

This change is prepared for the parent's consolidated follow-up deployment. No database writes, publisher retries or per-source GitHub runs were performed by this subtask.
