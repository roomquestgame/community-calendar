## 2026-11-16 — EVE-66 two-request Tavily content probe

Ben approved two Basic searches with include_raw_content enabled. Reuse durable reserve/reconcile accounting, fixed billing-review expiry, no retries or paid overage. Only two immutable content-probe-v1 jobs are admitted; other search jobs wait for review. Collector prioritizes these two jobs, requests five results, and stores bounded UTF-8 page content/snippets with original byte counts and truncation flags in private discovery-origin metadata. Search results remain unvalidated leads, not activity facts or public cards. Existing publisher scope, canary cutoff and counters remain unchanged. Restores token-validated gateway execute grants for the existing publishable-key facade after the pending dispatch wrapper.

45 focused Python tests and integrated isolated PostgreSQL dispatch/probe fixture passed, including two-request stop, duplicate reservation denial, immutable evidence replay, caller-role facade access and no publication. Production run/results pending; deploy collector first, then current-main Database deploy for both pending migrations. No GUI/native changes.

## 2026-11-16 — Event-driven queue delivery

Approved EVE-66 update: POST accepts only a database-issued, single-use dispatch ticket validated by the existing authenticated RPC. No arbitrary URL, source or client work request. Queue admission immediately invokes the bounded page worker; completion releases the dispatch ticket and wakes eligible work. Existing GET cron is recovery. Backend migration20261116110024 removes global pacing but retains per-publisher holds, health checks, leases, quotas and the original canary cutoff. Deploy this collector before the backend migration.32 focused coordinator/worker tests passed. Live trigger verification pending.

# Limited autonomous Things to Do pilot

Ben approved starting on a limited basis on November 15, 2026. This is the first
existing-source experiment for evergreen activities. General internet discovery
across metros and other towns remains disabled: this collector does not have a
deployed general web-search API integration.

## Scope and automatic operation

The existing Vercel collector has an authenticated GET endpoint at
`/api/things-to-do-pilot`. Vercel Cron invokes it every five minutes. It uses the
existing `CRON_SECRET`, Supabase publishable key and scoped collector token; no
service-role key or new paid API is added. Preview/local environments cannot
start real work. There is no URL, source, limit or budget in HTTP input.

The companion RoomQuestGame migration owns a finite, private inventory:

| Limit | Pilot value |
| --- | --- |
| Sources | Potomac Overlook, Upton Hill, Meadowlark Botanical Gardens |
| Lifetime | 72 hours from database activation |
| Global concurrency | One page job |
| Page attempts | 24 per UTC day; 60 over the pilot lifetime |
| Discovered pages | 40 total, restricted to those parks' activity paths |
| Staged activities | 100 total |
| Per page | At most 40 candidate records and 40 discovered links |
| Runtime | 45-second worker deadline inside the 60-second function |
| Lease | Two minutes, with stale-worker fencing |
| Refresh | Successful pages become eligible again after 21 days |
| Failure | Bounded retries; access/structure errors held for review |

The scheduler can run without an app visitor or this chat. The database rejects
new admissions after the lifetime/budget limit; the endpoint subsequently returns
a cheap expired/budget status. The cron definition itself remains configured
until this experiment is reviewed or superseded.

Ben set the evergreen recheck interval to **21 days** on November 15. A successful
page is scheduled from its last successful verification; a later existing wait
is preserved. Rescheduling does not change activity facts or observation dates.
New pages and failed-page retries keep their existing admission/retry rules.
The 72-hour trial still ends on November 18, before the first 21-day refresh is
due. The existing staged activities remain stored after collection stops.

The database checks current query/connection pressure, active event collectors,
provider work and eligible publication requests. It pauses on load or unavailable
telemetry and observes a cooldown before another admission. This is a small,
conservative admission guard, not measurement of Vercel CPU idle capacity or a
guarantee that other application work cannot begin after admission. A slow
database claim also prevents the Python worker from starting a publisher fetch.

## Collection and data quality

The worker reuses the collector's DNS, HTTPS, body-size, robots and publisher
pacing controls. The pilot disables page redirects so one admitted page cannot
expand into several document requests or a different park. A robots policy
request may also be needed. Holds and Retry-After/crawl-delay evidence survive
worker completion. No images, maps or booking pages are downloaded.

Activities need only a recognizable title, usable location and supporting
source URL. A known park plus city/state is enough for this pilot. Description,
photo URL, source categories, hours text, price text and booking link are optional.
Unknown values remain unknown; the crawler does not infer free admission, ages,
exact coordinates, current opening status, or dated event occurrences.

Drupal node identity is retained as `novaparks:node:N`. Different activities
sharing a listing page keep their distinct `#node-N` fragments. A record also
retains the page from which its facts were extracted. Listing and detail visits
upsert the same activity. Later sparse pages must not erase optional facts or
replace richer detail information with a listing teaser.

Only the activity article is parsed. Sitewide alerts, menus and booking promos
do not become activity facts. Donations are excluded; seasonal activities,
bookable experiences and records with sparse optional details remain candidates.
Unexpected markup is an explicit failure, not successful empty coverage.

## Reviewed category-intake evidence repair

The November 15 shared-category intake found three evidence gaps in the existing
32-record pilot. Detail extraction now retains the activity's bounded main and
additional narrative. For Field Trips, it also reads the explicitly named
**PROGRAM OFFERINGS** section in the single-column copy component. Booking,
fees, forms, separate grant sections and sitewide promotions remain excluded.
The Korean Bell Garden description therefore includes its garden and cultural
features instead of ending after the opening rental paragraph.

One exact parent-page job is additionally supported:
`https://www.novaparks.com/parks/meadowlark-botanical-gardens`. It reads only the
named **Visitor Center** accordion and supplies a description for the existing
`novaparks:node:293` identity. It discovers no links and does not create other
park activities. The companion database migration separately restricts this
job to a description-only enrichment with parent-section provenance; it keeps
the existing title, source URL, location and other optional facts.

Deploy this collector before the companion migration makes the two reviewed
detail pages and the one parent page due. The normal five-minute worker handles
those jobs under the same global lease, pressure checks, robots/DNS/redirect
guards, host pacing, budgets and fixed pilot cutoff. Every successfully fetched
page is parsed before completion even when its HTML hash is unchanged, allowing
an extraction fix to reach storage. Routine successful-page refresh remains
21 days. No general web discovery or manual worker invocation is introduced.

The focused parser/worker suite passes 49 checks, including both heading forms,
exact parent scope, unchanged-HTML reparsing, discarded administration and
retained sparse records. Replays of three inspected rendered DOM captures
support the reviewed descriptions; they do not prove live HTTP extraction.
The companion backend journal
`docs/journal/2026-11-15-shared-activity-category-intake.md` records the actual
deployment, scheduled run receipts and stored category verification separately.

## Review and release boundary

Outputs are private candidate records and run receipts in
`rq_curator_private.things_to_do_pilot_*`. There is no public-card publication,
event insertion, search change, saved-item change, itinerary change or mobile
release. Ben explicitly kept this workstream focused on crawling, storage and
refresh; he will start a separate chat for display mock-ups and integration.
This experiment measures initial extraction, detail enrichment and autonomous
operation. Its configured 21-day routine recheck lies beyond the finite trial.

The token-checked `community_collector_things_to_do` RPC supports `claim`,
`finish` and read-only `status`. Public database roles cannot read the private
tables. Status reports attempts, counts, expiry, the 21-day refresh interval,
health and run outcomes. It does not expose the collector token or a worker
lease token.

## Validation evidence

The initial saved-page replay produced **32 candidates**: 13 Potomac Overlook,
7 Upton Hill and 12 Meadowlark, with 17 scoped detail links. Field Trips survives
without a description, and distinct hiking/tree-hike fragments are preserved.
These are offline extraction results, not a claim of live staged records.

Focused Python checks cover required/optional fields, shared-page identities,
markup changes, source-local hours/fees, limited link discovery, robots/access
outcomes, deadlines, slow/unavailable admission, scheduler authentication,
redirect limits and authoritative completion outcomes. The companion backend
adds native PostgreSQL checks for leases, budgets, deduplication, enrichment,
pressure pauses and private permissions. Routine GitHub CI is not enabled.

The local shared-transport canary was stopped by this environment's DNS
validation (`dns_unavailable`) before a publisher HTTP request. That guard was
preserved. Production fetching and autonomous scheduling require observed
deployed run receipts; source HTML was separately available for parser research.

Production state and exact release evidence belong in the companion
RoomQuestGame journal `docs/journal/2026-11-15-things-to-do-pilot.md` and its
release receipt. Consult those dated receipts for the observed production
inventory and scheduler results.

The current refresh decision and its release evidence are tracked in
`docs/journal/2026-11-15-things-to-do-refresh-21-days.md` in RoomQuestGame.
