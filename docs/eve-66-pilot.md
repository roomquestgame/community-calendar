# EVE-66 limited pilot implementation — 2026-11-16

## Release preparation update

Ben configured `TAVILY_API_KEY` as a production-only sensitive variable and redeployed the old collector. Verified READY deployment `dpl_3squmCsNfRHzdv411xerEyQEz3wt` still serves `b5160221`; the key value was not retrieved. The missing-configuration blocker below is historical, not current. Authentication/free-only allowance remains to be verified by the deployed runtime.

A fifth migration seeds exactly twenty durable benchmark queries and enables search only. Publisher/feed/metro/gap/expansion/demand switches stay off and the canary clock remains unset. The coordinator can run that bounded benchmark while publishers are disabled; each query reserves once, with no retries of ambiguous outcomes. A non-secret preflight receipt records account-fence outcome and allowance. This is the first release stage; it does not activate publisher crawling.

Added a disposable native PostgreSQL multi-session fixture (`scripts/test-activity-concurrency.py`) for one active claim, budget admission, 100-view demand coalescing and expired-worker refusal. The local run is blocked by workspace socket permission (`PermissionError`); no native concurrency pass is claimed yet. A manual-only, secret-free GitHub diagnostic is included to run this specific fixture. No production load test is implied. Current focused collector result: 180 tests plus 49 subtests.



## State and scope

This batch implements an **inactive backend/collector foundation**, not an activated or completed canary. All discovery switches default false. No public activities, GUI files, mobile releases, production data, billing settings, or old pilot counters were changed by this implementation session. EVE-66's attached handoff and all nine children EVE-67–75 were read before implementation.

Baseline verified through read-only production tools:

| Surface | Observed state |
| --- | --- |
| App main | `6500cee391e424ce9fc7e96f0167e46e8c16ed43` |
| Collector main / production | `b5160221983e5de77963bec20ec71593d2f3ab95`, READY `dpl_J7HWmHXkNVGc2rtwvt7vxhzQb9yN` |
| eventquest.ai production | `fb01f82f249e9c49358b70fcb672e3ff12ed865c`, READY `dpl_J7yQSdqE1AmSsGjdLrQ3GVLbD91N` |
| Latest live migration | `20261116000302_things_to_do_reviewed_intake` |
| Data | 32 staged activities, 10 public, 21 pages, 23 lifetime / 3 UTC-day attempts |
| Original cutoff | `2026-11-18T14:57:28.068495Z`; unchanged |
| Metros | 387 existing CBSA records |
| Identity/fact evidence | Snapshot 2026-11-16 01:33:37 UTC; 0 saves; source-fact fingerprint `b78614fdef3ed7f35a9f0f40903628e5` |
| Search configuration | Collector environment metadata contains no `TAVILY_API_KEY`; no search request made |

The app main and website SHA are deliberately listed separately. A repository head is not deployment evidence. The old finite NOVA pilot remains the deployed behavior.

## Implemented code

Four additive CLI-created migrations add durable queries, canonical candidate URLs with multiple origins, private source scopes, a policy/version, request reservations, evidence, demand jobs, and bounded planners. They preserve existing UUIDs, catalog/saves, category triggers and legacy pilot history. No applied migration is edited.

The collector adds a pinned Basic search adapter and twenty-query search-only benchmark runner, a bounded general JSON-LD extractor and reviewed HTML fallback, shared pre-request admission, and a scheduled coordinator. Existing NOVA parsing remains separate and its regressions pass. Search snippets are leads only; publisher-derived core facts are required for staging. New records are not automatically published.

Limits are 24 primary requests/day and 60 total; 12 auxiliary/day and 30 total; 30 searches/day and 950/month with a target of 10/day; 40 new pages, 100 new staged activities, 10 domains, and 100 pending candidates. Reservations precede requests and uncertain search attempts retain their charge. Provider usage must establish a Free account and zero paid overage; otherwise search fails closed. No code changes billing. The shared page lease and global lock remain in use. General redirects are disabled; existing narrowly approved robots redirects also require admission and are bounded to three hops.

Core evidence is separate from sightings and is due after 90 days on demand. Operational evidence is due after 30 days or explicit validity. Unknown historical verification is not backfilled. Read RPCs remain read-only; a separate known-ID demand facade is defined but execution is withheld until client integration is ready. Completed demand history does not block a later eligible request. Successful v2 pages have no periodic next attempt. Closure expiration does not imply reopening. Coarse locality fields are additive; no coarse public venue is created in this batch.

The feed planner seeds two verified organization hosts from existing source IDs 5115 and 5111. Metro scopes derive from the 387 CBSA records but all are disabled. Locality inventory is explicitly limited to South Hill and Chase City; unknown population is retained. Queries rotate by least explored scope and a durable five-family cursor. Metro-wide leads require reviewed locality mapping before publisher admission; they are not assigned a guessed town.

## Focused verification

- Collector: 179 focused tests passed plus 49 subtests. Coverage includes new search, extraction, request admission and coordinator behavior and existing NOVA/worker/robots behavior. No GitHub CI was dispatched or label added.
- Two isolated PostgreSQL/WASM fixtures passed with PGlite 0.5.16: migration application, claim/reserve/intake, query reserve/receipt, receipt replay, benchmark reseed idempotency, bad lease/off-scope refusal, 89/91-day demand, 100 sequential demand coalescing, completed-work requeue, 24/60 and 12/30 publisher caps, 30/950 search caps, expired pilot, private grants, unknown legacy freshness, stable public ID, town-center address semantics and persistent expired closure.
- These are focused fixtures with schema stubs, **not** a full-schema replay, real multi-session concurrency test, live failure injection, category acceptance review or 72-hour observation. The repeated-demand check is sequential, not a concurrency claim.
- SQL runners: `scripts/test-activity-foundation.mjs` and `scripts/test-activity-pilot.mjs`. Supply `PGLITE_MODULE` pointing to an installed `@electric-sql/pglite` module. Production dependencies are unchanged.

## Remaining work and release order

1. Review and integrate the paired PRs through normal PR protections. Recheck current main and migration ordering; preserve concurrent GUI changes. No `ci:validate` or routine CI.
2. Deploy the disabled backend through current-main `db-deploy.yml`, retaining exact history comparison, ordered dry-run, push and verification. Do not apply these via ad hoc production SQL. Deploy the paired collector and verify its actual SHA/route state. Neither deployment has been performed by this session.
3. Configure a server-only Tavily key in the collector's production environment through the owner's secure configuration path. Do not paste secrets into Linear, source, or chat. Verify the account-wide Free/zero-overage fence and shared usage. This is a live prerequisite, not a reason to change billing.
4. Enable only search for the search-only benchmark via a reviewed migration/receipt. Run `python scripts/benchmark_things_to_do.py --execute` using server configuration. Review all 20 search outcomes and report denominators, candidates, duplicates, unusable/off-location results, credits and uncertainty. Do not fetch publishers during this benchmark. The dry-run is safe without credentials.
5. Complete minimum demand-signal integration with the separate GUI work: viewport/detail/saved/itinerary signals must be fire-and-forget and must never delay cached rendering. Grant the demand RPC only with that release. Native integration goes to both iOS and Android Preview before any authorized Production promotion. No mobile production release is authorized by this backend batch.
6. Before activation, add reviewed locality mappings for selected DC leads, select transferable existing NOVA pages explicitly, and record policy/source/SHA/benchmark receipts. Do not reset old counters or silently rearm. A separately committed activation must set one fixed window of at most 72 hours and the exact DC/South Hill/Chase City scopes. The current migrations intentionally do not activate anything.
7. Run the finite canary through the ordinary scheduler, recording publisher-validation duration separately from autonomous-operation duration. Verify multi-session fencing/budgets, pressure pause, immediate cached behavior and comparable foreground latency/errors. Review actual locality/category/extraction quality denominators and save/UUID preservation before publishing any new activity. Broader 3/25/387 rollout stays disabled.

Additional incomplete contracts: conditional 304 representation reuse is not implemented (a 304 is not treated as verification); generic geocoding/venue publication is not enabled; source-specific evidence-level/HTML mappings require review; historical operational labels and closure-specific itinerary UX remain with the minimal client integration. These are not claimed complete.

## Operational and rollback contract

The token-protected discovery `status` action exposes flags, request counts, pending demand/candidates and oldest timestamps, query/candidate outcomes, current-month search units and uncertain searches. Existing pilot status retains health and worker receipts. Detailed ledger/origin/evidence rows are private and must be queried only through authorized operator access.

Independent switches control feed, metro, gap, expansion, demand and search. Disable new-policy work without deleting cached public catalog/saves or clearing reservations. Do not extend `ends_at`, reset counters, refund ambiguous attempts, or reopen closures because a notice expired. Keep the old cutoff/history intact. Any corrective production flag changes must follow the committed release process.

The required external collector guidance paths `.claude/bram-conventions.md` and `app/__shell/conventions.md` were absent at the observed repository state; no replacement conventions were invented.
