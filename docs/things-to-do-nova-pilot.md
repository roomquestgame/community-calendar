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
| Refresh | Successful pages become eligible again after 24 hours |
| Failure | Bounded retries; access/structure errors held for review |

The scheduler can run without an app visitor or this chat. The database rejects
new admissions after the lifetime/budget limit; the endpoint subsequently returns
a cheap expired/budget status. The cron definition itself remains configured
until this experiment is reviewed or superseded.

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

## Review and release boundary

Outputs are private candidate records and run receipts in
`rq_curator_private.things_to_do_pilot_*`. There is no public-card publication,
event insertion, search change, saved-item change, itinerary change or mobile
release. This experiment measures extraction and autonomous repeat operation
before the new card type is integrated with those product flows.

The token-checked `community_collector_things_to_do` RPC supports `claim`,
`finish` and read-only `status`. Public database roles cannot read the private
tables. Status reports attempts, counts, expiry, health and run outcomes; it
does not expose the collector token or a worker lease token.

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
release receipt. Until those receipts exist, this document describes the
implemented behavior rather than claiming a running deployment.
