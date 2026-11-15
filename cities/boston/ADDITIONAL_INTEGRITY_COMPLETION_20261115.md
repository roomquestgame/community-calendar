# Boston additional calendars — publication completion, 2026-11-15

This release completes remaining defects in the 21profiles already enrolled by the concurrent Boston release (collector PR #229, database migration 20261115010603). It preserves the NYC additions in PR #230 and the subsequent four-source completion in PR #232 (main 893ab34db65ab7d10697ecae598419cd19650ddb). Source enrollment and working published data are preserved.

## Production verification and final venue completion

The 21-profile batch is enrolled. Collector PR #231 and successful [database run #316](https://github.com/roomquestgame/RoomQuestGame/actions/runs/43664812246) shipped the integrity fixes described below. The shared City Natives follow-up is also live through collector [PR #234](https://github.com/roomquestgame/community-calendar/pull/234), backend PR #944 and successful database run #317. The released City Natives mapping and its original provenance are preserved; the redundant local candidate was not released.

Independent production checks confirm all 101 eligible outdoor/community records and all 216 reviewed Burren, Passim, Lizard and Long Live records. The two City Natives workshops are public with exact publisher destination coordinates and unchanged native descriptions, clocks and streets. The 64 exact obsolete representations remain excluded/hidden, with native facts, manual overrides and the original Arts at the Armory event retained.

Eliot School recovered from transient database RPC timeouts through normal checkpoint continuation, completed all 24 full native records and cleared its checkpoint. The 02:03:37 UTC whole-cohort readback contains 721 active public events with zero blank descriptions, description mismatches, missing postal streets or missing coordinates. Exactly one included occurrence remains held at that snapshot: Introduction to Sharpening at Boston Building Resources, 100 Terrace Street, Boston, MA 02120. The other 23 Eliot occurrences are public.

The final point correction binds only that exact Eliot source/venue/street to City of Boston SAM address ID 134497, OBJECTID 215912, point `42.328649,-71.097821`. It preserves the complete 2,644-character native description and all event identity/time fields. Schoolhouse and Annex keep their already working resolution. The paired backend correction uses the established source-specific reviewed-venue mechanism and ordinary publication from the complete snapshot; no publisher refetch, global geocoder-cache write or source-preview reset is required.

The [coordinating backend completion report](https://github.com/roomquestgame/RoomQuestGame/blob/main/docs/boston-additional-integrity-completion-20261115.md) contains final deployment IDs, current active-public counts and post-publication acceptance. The counts above identify the reviewed pre-correction snapshot.

- [Final community production verification](../../docs/evidence/boston-community-additional-integrity-fae-production-20261115.json)
- [Nightlife production verification](../../docs/evidence/boston-nightlife-additional-integrity-production-20261115.json)

## Remaining changes

- Burren: retain the newly deployed explicit comma-separated showtime parsing and full linked-detail hydration, with stricter malformed/duplicate clock validation. Fresh capture:123 complete occurrences. Fresh rows use Somerville's exact named-building point; a fully validated in-flight legacy prefix retains its existing fields and progress.
- Parkour: replace two misleading aggregate listings with six individually dated, admissible native sessions; preserve four ordinary identities and use the reviewed exact Dojo point.
- Rock Spot South Boston: exclude 61later course installments requiring prior enrollment; retain 75independently joinable records and the exact publisher gym point.
- Central Rock Cambridge and Long Live Roxbury: preserve the verified points and provenance added by PR #232; conditional database refreshes skip any already-published rows. Descriptions and event identities remain unchanged.
- Club Passim: remove only the exact offsite Armory overlap already covered by the original venue source. Preserve all 60retained records and the deployed Passim point. A validated legacy checkpoint can upgrade in place without restarting.
- Arts: add full per-occurrence checkpoint integrity proofs while retaining all 285captured deployed outputs. An untouched empty legacy prefix upgrades safely; only an actually present processed legacy generation needs a conditional reset. Raise only Coolidge's checkpoint event allowance to 500; manifest 200 and 900 KB limits remain.
- Lizard Lounge: preserve the preceding-local-date query for overnight occurrences and use the exact municipal address point. The timeout itself is not a parser defect. A bounded check of the original permitted endpoint recovered to HTTP 200; the paired migration permits one ordinary retry only for its exact exhausted504 state. Production recovery must be verified separately.

## Verification and release ordering

The combined focused suite passes 122 tests and 92 subtests. Captured worker replay and frozen-output comparisons are in the linked evidence. These are offline/captured checks, not a claim that the release is serving or that every publisher is reachable in production.

1. Merge this completion batch and deploy the exact merged commit to the collector's production alias.
2. Confirm READY before the guarded database completion migration.
3. Preserve active leases; conditionally refresh only actual remaining targets through one ordinary batch wake.
4. Read back current published identities, complete description hashes, streets, coordinates, diagnostics and queues.

Arnold Arboretum's actual publisher HTTP 403 remains paused. The Aquarium currently has no eligible available public programs. One BAC event with conflicting weekday/date remains held. Never invent a description or resolve an ambiguous time by guessing.

## Evidence

- [Combined focused integration receipt](../../docs/evidence/boston-additional-integration-20261115.json)
- [Arts reconciliation](../../docs/evidence/boston-arts-additional-reconciliation-20261115.md)
- [Community reconciliation](../../docs/evidence/boston-community-additional-reconciliation-20261115.json)
- [Gym point evidence](../../docs/evidence/boston-community-additional-gym-points-20261115.json)
- [Nightlife reconciliation](../../docs/evidence/boston-nightlife-additional-reconciliation-20261115.md)
- [Municipal Burren and Lizard points](../../docs/evidence/boston-community-additional-nightlife-points-20261115.json)

The coordinating backend release owns exact 64 representation-withdrawal fences, current source/rights/coverage gates, every manual override guard, and the single production database workflow. No direct SQL production mutation is part of these collector changes.
