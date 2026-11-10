## Civic and public services — November 10, 2026 (prepared)

The reviewed civic cohort adds Richmond/Alexandria meetings, Virginia public
calendars, Clarksville dated notices and South Hill public works through the
existing collector. Verified service rules expand into eight weeks of dated
notices with stable identities and explicit holiday exceptions. The existing
South Hill calendar gains opt-in administrative notices; finite civic ICS
support is available but no new ICS source is enrolled.

Read [the civic source contracts and audit guide](../docs/civic-services.md)
for official URLs, coverage limits, capability gating, date/expiry semantics,
the v2/v3 pipeline and manual `civic_live` verification. The combined local run
passed 507 tests and 30 subtests, after a reviewed baseline of 473 tests and
30 subtests. All seven guarded workspace probes returned `dns_unavailable`.
New registrations remain pending; these checks do not establish deployment,
live collection or publication.

## YMCA class description order — November 9, 2026 (prepared)

YMCA narratives now lead with the publisher's specific class description and
schedule, followed by the full-session note and then the general program text.
The 2,000-character limit reserves room for the complete full-session note.
Repeated general text is omitted when it matches the specific text after
whitespace and case normalization. Full publisher text is still validated
before truncation; occurrence dates, identities, venue and audience evidence
retain their existing extraction rules.

The current official [Dance page](https://mecklenburg.recliquecore.com/programs/37/dance/?locations=-1)
was read on November 9 and matches the captured specific ages 3–5 description
and Wednesday 4:45–5:30 p.m. Clarksville schedule. Its six occurrences retain
the full publisher prose in 957 characters. Local validation passed 84 YMCA
and Mecklenburg pipeline tests, including long descriptions, duplicate or
missing general text and unchanged structured fields. All seven captured YMCA
records differ from the baseline only in description. Collector deployment and
the companion six-record database refresh remain separate release steps.

## Raleigh–Durham catalog activation — November 8, 2026

Legacy Raleigh–Durham ICS entries now use the same bounded robots-aware publisher transport as the reviewed Raleigh cohort. The collector checks the exact catalog URL and publisher host before fetching. The companion activation migration enrolls permitted feeds in search discovery and leaves explicit publisher blocks outside the activation list.

## Raleigh catalog feed recovery — November 8, 2026

Seven exact Raleigh-area calendar keys use the existing bounded ICS transport with publisher robots and same-host redirect checks. The normal worker retained descriptions for 226 timed candidates in captured feeds. The companion database migration supplies search coverage and the shared address path for these existing Mapsee and Udell registrations. Counts precede address resolution and publication.

## Raleigh first approved source batch — November 7, 2026 (prepared)

Eight exact public calendars now have a bounded HTML adapter. JSON/ICS export
URLs excluded by Squarespace robots are never fetched. Fixed-date replay gives
83 candidates from seven sources, with original image candidates; missing
venues and conflicting dates are held without source-center pins. Black Chamber
remains paused for conflicting gala evidence. Both bookstore calendars retain
visible event addresses and bounded optional detail enrichment. Shared v3
staging, categorization, geocoding, image probes, demand and freshness remain.

Local provider suite: 1,547 tests and 37 subtests pass; five Vercel build-selection
tests pass. These are parser/worker tests, not deployed transport or publication
proof. The companion backend migration starts seven registrations pending and
Black Chamber paused/disabled. Use the existing manual provider workflow's
`raleigh_live` option after collector release to collect read-only transport
receipts. No database credentials, demand, staging or publication are part of
that audit. The authenticated workflow browser is currently unavailable.

See [the source contracts and replay provenance](../tests/fixtures/raleigh/README.md).

## Mecklenburg reviewed sources — November 6, 2026 (two ready, one held)

Rosemont through WordPress JSON and Chase City Chamber through its allowed normal
HTML calendar are the two sources eligible for active registration. Their local
captures produce three and one candidates. Mecklenburg public library parser
work is retained dormant: Google robots explicitly denies the feed path, so the
source must remain paused, disabled and outside discovery routing. Its exact
source key now requires robots checks before any calendar HTTP request.
The 29 parsed candidates comprise four eligible active-source candidates and
25 held library candidates; they are not a production-publication count.
Closures, private events, conflicting schedules and unreviewed venues are held
or excluded. Local DNS restrictions prevented actual collector transport proof.
Rosemont and Chase City use the existing bounded publisher-image candidate
protocol. Library page artwork is not treated as event imagery. No export path
disallowed by robots, new timer or default event pin is introduced.
See [the source contracts, evidence and release boundary](../docs/mecklenburg-source-batch-20261105.md).

## Virginia event descriptions — November 5, 2026 (prepared)

The Virginia HTML adapter now reads the event's actual narrative, preserves a
concise meeting point, and carries explicit publisher categories, fees,
children-welcome, and registration evidence for shared backend classification.
It uses the already-fetched detail HTML and preserves the existing photo-v2
pipeline. A bounded, read-only manifest capture supports a fingerprinted repair
of existing records. See [the extraction contract and capture limits](VIRGINIA_EVENT_DETAILS.md).
Production release and repair evidence are tracked by the companion backend release.

## Dedicated event-image worker — November 5, 2026 (prepared; not deployed)

The candidate-only Virginia image lane now has a ticketed `/api/media-demand`
entrypoint and an independent bounded runtime. It fills free execution slots
throughout the run instead of stopping after three candidates on every third
geocoder tick. Database settings select five workers by default, with a hard
ceiling of ten, and three requests per publisher host. One active database drain
lease, candidate-host admission, and a shared redirect-host limiter bound total
concurrency. Each executor thread reuses its own HTTP Session. No async runtime
or new HTTP dependency is introduced.

The worker still verifies only a 4 KB prefix of the already extracted publisher
image and stores its validated URL. It never downloads a full image into storage,
refetches a Virginia event page, or renews the 96-hour source evidence clock.
Temporary network errors, HTTP 429/5xx responses, exhausted time and occupied
host slots defer work instead of recording a permanent missing image. Result
counts require a database acknowledgement. Fixed counters and elapsed time go
to structured stdout without tickets, tokens, publisher URLs or event text.

Deploy this backward-compatible collector first. Until the backend explicitly
reports `dedicated_ready: true`, the existing geocoder photo stage remains the
fallback. The companion database release owns enabling dispatch after source
publication commits, bounded continuation, host backoff and recovery. The new
worker depends on production mode and database admission, not the geocoder flag.
See [the media protocol and operating limits](MEDIA_WORKER.md).

## Shared JSON-LD collector — November 1, 2026 (prepared; not deployed)

Ben approved JSON-LD next. Read-only inventory: 89 Mapsee JSON feeds, seven completed (one location gap), 58 unsupported embedded payloads, seven unsupported event shapes, ten unresolved timezones, four invalid payloads, one oversized response, one blocked redirect and one robots denial. Six completed feeds have usable location evidence. Registered/source-ready/collector-complete/public-visible are separate milestones.

The family now dispatches before catalog provenance, and legacy Mapsee calls delegate to one JSON-LD module. It reads one registered page/JSON response, supports script quote/case/MIME variations, raw JSON, type arrays/schema URIs, nested event/list/graph containers and local venue/address/geo references. The factual normalizer, original IDs/occurrences/links/categories/venue signatures, 60-day window and source-scoped caches remain. Existing malformed-description repair is retained, but unreadable blocks cannot silently produce a healthy partial snapshot. Conflicting definitions, multiple physical venues, missing timezones and invalid dates remain review failures. Same-ID distinct occurrences are preserved. No JavaScript, extra-page crawl, remote context/reference fetch, extra scheduler, geocoder or default pin. Page extraction is not exhaustive website coverage and absence never infers cancellation.

The companion migration reuses existing intake columns and the shared cache-aware location check. Robots denial deactivates/hides that old route; other failures and nonempty location gaps pause with reasons. Healthy structured empties remain ready. The 65 still-approved payload/shape failures receive one explicit validation cycle after the parser repair, through existing demand worker/leases/cadence/budgets. Rechecks preserve concurrently paused/recovered sources. Failure then stops in review; no arbitrary review row is released. Existing data, overrides/categories, saved IDs/links and current referenced-event retention rules remain. No app/Edge change or activation of new/unreviewed sources.

Preflight passed: 68 Python tests, py_compile, full isolated 190-migration PostGIS replay, ten SQL behavior suites and actual migration queue/operator-pause checks. Final-head native CI and guarded fresh-live-schema DB rehearsal remain required. Deploy the backward-compatible collector from tested GitHub main first, then Database from main for 20261101212219; actual recovered counts and public results remain unverified. Workspace protected publisher probes have a known DNS limitation; do not turn that into source failure evidence.

WordPress and Squarespace are already deployed. Latest Squarespace verification recorded 19 ready, 26 review, 15 queued and two earlier paused registrations; twelve post-release successful source checks establish actual processing, including two valid empties. Preserve current Pulse/Afterglow and referenced-event history changes. After JSON-LD come smaller RSS/library/ChamberMaster formats and ICS last.

## Shared Squarespace family — November 1, 2026 (prepared)

The JSON family now selects one collector before Mapsee provenance. Legacy Mapsee calls delegate to it, while Frazier and Mission retain their stricter reviewed location/timezone checks. Registered URLs preserve selectors and normalize one format=json parameter. Only an explicitly proven separate past-archive cursor is omitted; unknown/incomplete pagination fails into review. No archive/per-event crawl, new Cron or geocoder. Original event/source IDs, venue signatures, factual categories, cached locations, 60-day window and current source/staging bounds remain. Conflicting marker/map coordinates are held instead of guessed.

Inventory is 58 Mapsee plus four other community feeds. Seven previously completed sources remain eligible (one empty); the companion app migration gives the 45 old archive-cursor failures one demand-worker validation cycle and holds eight other failures. Avondale and the duplicate Waimea registration stay paused. Actual recoveries/public visibility remain unverified. No provider is silently activated. Subsequent robots denials deactivate; other failures or unresolved nonempty locations pause for explicit review using the same address/manual/reviewed caches.

Preflight: 55 Python tests, full isolated 186-migration PostGIS replay, nine SQL suites and the actual migration revalidation/paused-source checks pass. Publisher probes from this workspace returned dns_unavailable; this is an environment limitation, not a new source result. Final-head CI and production release receipts belong on the release PR. Deploy this backward-compatible collector from GitHub first, then the guarded app Database migration 20261101194641. READY is separate from fresh queue, cache and public-listing verification.

## Shared WordPress / The Events Calendar collector — November 1, 2026

WordPress JSON feeds now select `wordpress_adapter` by adapter family before Mapsee catalog routing. The legacy Mapsee Tribe call delegates to the same collector; catalog provenance, source keys, factual parser and downstream staging/publication are retained. Root and complete API URLs preserve publisher filters, use the existing 60-day window, and rebuild registered-host pagination without following response links. Bounds remain five pages/500 facts and the existing worker deadlines. Only all successful staging checkpoints permit a healthy snapshot; valid empty responses stay healthy. Malformed records still fail the source into review rather than claiming a partial complete snapshot.

Companion app migrations `20261101184455` and `20261101191616` deactivate robots denials and pause technical/location failures with explicit review reasons. Exact supplied/manual locations, normalized address cache and the approved 3,534-entry venue batch are reused. No geocoder, scheduler, publication gate, identifier or location default is added. RSS and the two unreviewed non-Mapsee JSON feeds remain paused. Curated direct WordPress sources retain their own venue mappings; the sole overlapping JRA Mapsee route pauses only when fresh direct-home events exist. Its existing direct window is 30 days and longer-window parity remains review work.

Local verification: 33 Python tests, full 185-migration isolated PostGIS replay, and eight SQL disposition/publication/identity/cache suites pass. A label-triggered, read-only provider test workflow validates the final PR head without enabling upstream automatic workflows. Merge/build is separate from a real source refresh: record the Git-connected Production deployment receipt on the release PR, deploy the companion app migrations through its guarded Database workflow, then read back actual source outcomes. No public activation or native/website release is implied by this entry.

## Deployed provider pilot — October 30, 2026

The approved Orangeburg, Frazier and Mission Garden collectors are deployed and their controlled intake is verified: 18, 10 and six privately staged events, respectively. Orangeburg has 14 venue addresses but zero coordinates; all 18 remain held. Udell publisher job 33 stays inactive; no collection Cron, publication cohort or provider activation was added. Read [the verified release receipt](../docs/provider-release-20261030.md) before older prepared/pending notes below. The applied companion migrations are 20261030101923 and 20261030101930, released by app database deploy 41045737873.

## Selected Squarespace JSON calendars — October 30, 2026

Ben approved Frazier History Museum and Mission Garden only, following the
nine-endpoint evaluation. Waimea Valley, Avondale, Buffalo and the three library
endpoints are outside this batch. The collector reads the public JSON response
directly; no HTML scraping or per-event detail requests are added.

The adapter admits exactly the two reviewed URLs, verifies publisher timezone,
retains stable IDs, event links and source start/end timestamps, and uses the
existing 60-day window and private staging RPCs. Frazier's past-archive cursor is
accepted only when it matches an explicitly past record; an unknown cursor fails.
Intake is bounded to 100 upstream records, matching the existing staging batch.
Unpublished, cancelled and all-day records are excluded. Event-specific address
and marker coordinates are retained only with a complete in-state street address
and coordinates within the source's reviewed state bounds. These bounds detect
obvious conflicts; they are not independent street-level geocoding. Missing or
conflicting coordinates are held without a substitute pin. Off-site Frazier
locations, including Copper & Kings, retain their own address and coordinates.

Direct publisher JSON snapshots produced 10 Frazier and 6 Mission Garden events
inside 60 days, all 16 with source-provided coordinates. Mission Garden's other
two upcoming records fall outside that window. No descriptions or images are
copied into staging. The two-source data migration reuses Metros5 URL-derived
keys, so applying its older catalog later cannot duplicate the sources. Only
these two JSON rows are approved; other Metros5 feeds retain their existing state.
Source timezone is explicit; publisher rights remain unreviewed and default pins
remain absent. The existing collector handles previews; no Cron, geocoder cohort
membership or publication scope is expanded.

Local validation: 106 Python tests plus 10 subtests passed, py_compile and
git diff --check passed. The full local PostgreSQL/PostGIS migration replay and
provider/staging/discovery suites passed, including the updated Metros5 source
selection assertions. Final-head CI and the fresh production-schema release
gate remain required. The protected transport has not been verified end-to-end
against these publishers from a deployed worker.

Deployment is still blocked by the previously recorded unrelated pending
migration history. No database write, collector deployment, live private intake
or public event publication was performed for this batch. Merge and deploy are
separate from actual map visibility; do not report these 16 events as live.

## ChamberMaster provider — prepared, not activated (October 29, 2026)

Ben approved one separately managed ChamberMaster API provider with Orangeburg
as its first source. `/api/chambermaster` uses the existing operator/Cron secrets
and the scoped collector token; callers cannot choose URLs or source IDs. It
claims one chamber from the new protected registry gateway and stages facts
through the existing RPCs. The public XML schedule is parsed by Udell's actual
GrowthZone code; bounded event-specific iCalendar exports supply event venue
text, with matching EventID and exact start time required. No chamber-wide
coordinates, descriptions, photos, geocoder grants or native events are added.

Deploy the companion `20261030091253_chambermaster_provider_registry` migration
and validate its exact token-gated wrapper/security exception before invoking
this endpoint. The global provider and Orangeburg source begin disabled/pending;
no collection Cron is added. Admin API health shows the separately managed
provider and source controls reuse the existing Data registry. A successful
private preview is not public geographic publication. The existing community
publisher job remains paused. See [provider contract](../docs/chambermaster-provider.md).

Local validation on October 30: 83 Python tests and 10 subtests passed.
The full current-main app source passed typecheck, lint (six existing warnings),
238 unit tests and 31 integration/configuration tests. All 152 migrations replayed
in local PostgreSQL/PostGIS (PGlite/PostGIS 3.6), followed by ChamberMaster,
community, curator, Localist, map/discovery, geocoder, RLS and Udell SQL suites.
Authorization, disabled/idle behavior, valid-token claims, private staging,
source approval/pause/restrictions, duplicate leases and daily budget are covered.
This local replay does not replace CI's PostgreSQL 16/PostGIS 3.4 or the required
fresh production-schema rehearsal. Final-head CI, production-schema rehearsal,
merge, database release, collector deployment and live preview remain pending.
The GitHub connector cannot dispatch workflows; no deployment credentials are
available locally. Do not bypass the manual release or repair unrelated migration
history. The new migration is 20261030091253_chambermaster_provider_registry.

# RoomQuest community collector

## Staggered collection closeout (October 28, 2026)

The same five preview jobs now start at successive minute offsets, each still
once every five minutes: preview-1 at minute 0 modulo 5 through preview-5 at 4.
That preserves 60 collection invocations per hour and all source/thread/deadline,
authentication, retry and shared Geocodio limits, while avoiding five simultaneous
collection starts. The existing geocoder still runs every minute. This is load
smoothing, not evidence that the remaining production SQL timeouts are fixed.

Before this change, main PR #314 / migration 330000 deployed successfully via
protected run 40711215340 (131 aligned versions, 82 SQL suites). The 11:05 a.m.
Eastern publication succeeded in 101.518s, 11:10 failed at 120.148s, and 11:15
succeeded in 112.547s. Some actual geocoder runs still returned 503; photo runs
continued. Backend discovery and cached Colma/Durham/Richmond points passed, with
one reservation per tracked address. Production must be verified after READY;
no monitoring-only completion is claimed here. See the main repository's
`docs/mapsee-closeout-20261028.md` for the operating handoff.

## Unified venue resolution batch (October 27, 2026)

The existing minute job rotates dedicated geocoding, venue-resolution (then geocoding with remaining budget), and event-photo batches over three minutes. Each invocation stays within its existing 45-second budget. It claims one source-scoped venue
identity and examines at most two publisher/event pages for exact-event JSON-LD location evidence
or matched-venue structured/contact addresses. It may follow a publisher-local venue/contact link.
Generic rooms, conflicting locations and unavailable evidence go to the real Admin Data venue queue.
No external search subscription, new geocoder, extra Cron, or service-role credential is introduced.

The companion RoomQuestGame migration `20261028120000` stores verified addresses/evidence for reuse,
preserves raw publisher room/address text, invalidates changed venue signatures, adds protected
administrator review and reuses existing address/quota caches for every matching future occurrence.
Deploy that migration before this worker. Older address-only geocoding continues to use the same
reservation ledger and exact provider-evidence checks. Only verified locations enter normal nearby
discovery; the separate Events directory section is removed in the app batch.

ICS CATEGORIES now decodes to real publisher labels, and structured addresses retain city/state/ZIP.
Run `python -m pytest tests/test_roomquest* tests/test_forward_geocoder.py tests/test_venue_resolver.py`.
The 16 new fixtures cover evidence identity, conflicting addresses, bounded/publisher-local lookup,
room labels, complete address extraction and real iCalendar category decoding. Existing minute
cadence is unchanged; its old five-minute test expectation has been corrected.

The photo worker remains scoped to the original 400 feeds. The separate Mapsee eligibility migration explicitly extends the shared venue resolver; this collector release alone does not enroll sources in geocoding. The separately merged Mapsee collector adapters, cadence and bounded staging are preserved.

This adapter preserves the upstream Python scrapers and supplies restricted RoomQuest ingestion and forward geocoding. The original 400 Jon Udell feeds remain intact. The Mapsee extension adds a pinned, positively identified US catalog through the same collector and normal Events process.

## Server configuration

Vercel Production uses SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY and ROOMQUEST_COLLECTOR_TOKEN. The token's SHA-256 hash lives in Supabase's private preview_credentials table. Never configure a Supabase service-role key here. Existing CRON_SECRET authenticates scheduled GET requests; ROOMQUEST_PREVIEW_SECRET authenticates bounded operator POST requests. Never print, download or commit these secrets.

Geocoding additionally requires the existing Sensitive Production GEOCODIO_API_KEY and explicit FORWARD_GEOCODER_ENABLED=true. VERCEL_ENV must be production and the private database settings row must also be enabled. Public health GET reports booleans only. The key is sent only in a Geocodio Authorization header, never a URL or log.

## Ingestion

The existing five preview Cron jobs run every five minutes at successive minute offsets and claim up to four sources each. The worker preserves future factual title/time, publisher attribution, original link and supplied venue details. It uses the upstream recurrence expansion and supported ICS, JSON-LD, Tribe and GrowthZone adapters, with existing robots, HTTPS, DNS/IP, response-size, timeout and no-redirect safeguards. Its two existing token-scoped preview RPCs write private staging metadata and diagnostics. The separately scheduled Supabase factual publication job writes eligible factual records to existing external_events; verified coordinates enter normal Events/Home/Map discovery. Publisher descriptions, fictional hosts and RSVPs are not created. Original-cohort event image URLs use the bounded photo pipeline below.

## Forward Geocoder

Vercel Cron invokes GET /api/geocode every minute using its existing CRON_SECRET bearer convention. POST uses ROOMQUEST_PREVIEW_SECRET. Neither accepts caller-supplied addresses, URLs, IDs or a body. An unauthenticated GET is health only; unauthorized invocation cannot start work.

The Python framework uses one pyproject.toml entrypoint, api.index:handler. Its dispatcher routes geocoding to api/geocode.py and retains all existing preview slots; adding an API file or rewrite alone does not register a second Python application.

roomquest/forward_geocoder.py calls only the new community_collector_geocoder RPC for claim/reserve/submit/fail/status. Its public invoker reaches an unexposed token-validating gateway; no private function is called through public REST. The collector cannot edit settings or arbitrary events. Each unique complete US physical address has one durable private queue/cache row. New and previously imported original-cohort facts enter the same pipeline. Venue-only or incomplete addresses use the shared official-evidence venue parser and admin review queue, without guessed map pins. Mapsee is never added to the legacy separate calendar directory.

The one-minute schedule increases backlog throughput without increasing the per-invocation bounds or shared daily allowance. Once the queue is empty or quota is exhausted, invocations stop before contacting Geocodio.

The worker claims one address at a time, reserves a quota slot before every outbound request, uses Geocodio /v2/geocode with an eight-second timeout, and processes at most ten requests within a 45-second budget inside the 60-second Vercel function limit. It never retries HTTP automatically. Durable transient retries back off and stop after five attempts; ambiguous matches stop, 429 pauses until the next UTC day, and provider-auth errors pause for an hour. A crash leaves an expiring lease and a consumed reservation.

The database serializes reservations across all workers and enforces both a server UTC-day and rolling 25-hour-plus-30-second cap of at most 2,300 attempted requests, including failures and retries. Quota exhaustion stops processing automatically. No paid-overage, batch-geocoding or field-append feature is activated. Rooftop/point matches require score >=0.9, exact event street/city/state and US country evidence, valid coordinates and no conflicting close candidate. Publisher headquarters/region never substitutes for an event venue. Cached verified coordinates and provider evidence are retained for reuse, written to existing external_events.location, and preserved by the factual-refresh trigger. Native events and other providers are excluded.

## Release and checks

Deploy RoomQuest PR #285 through its protected database workflow first; it reconciles the explicitly audited history records and applies the disabled geocoder migration without bypassing schema gates. Verify the private cohort is exactly 400. Start with database daily_cap=3 and enabled=true, then deploy this collector with the Production switch enabled. Confirm key presence through metadata/health, actual Cron requests, ledger/provider evidence, correct geographic discovery and refresh persistence before raising the database cap to 2300. See RoomQuestGame/docs/udell-geocoding-rollout.md for the complete runbook. A READY deployment alone is not processing evidence.

Run focused tests locally with python -m pytest tests/test_roomquest* tests/test_forward_geocoder.py. The main repository also runs rollback-only SQL authorization, address/cache, discovery, refresh/provider-regression and concurrent quota tests. Review actual Vercel usage when changing schedule frequency. Upstream GitHub Actions remain disabled, and the ignored-build command skips nonproduction builds. Health and batch responses expose aggregate counters only; operational queue/usage status requires the restricted collector token or a privileged database operator.


## Public event photos

Owner explicitly authorized automatic photos without a separate source-image permission approval
step. Feed image attachments and publisher JSON-LD/WordPress image fields are staged privately.
The photo phase also checks exact event-page JSON-LD, event-matched Open Graph and featured images.
It claims at most three source/event identities, validates public HTTPS/DNS/redirects, MIME and
image-file signatures, reads only a 4 KB prefix, and rejects logos/tiny tracking pixels/oversized files.
Successful URL evidence is cached for seven days and reused across refreshes and recurring events.
Pictures display through existing normal event cards; unavailable pictures keep the existing fallback.
Deploy companion migration 130000 before this worker. The existing minute Cron and all Geocodio
reservation/cost limits remain intact; no files are copied to Storage or new search service added.

Photo tests: `python -m pytest tests/test_event_media.py`. Focused venue/photo suite: 67 tests plus ten
subtests; the combined suite also includes the Mapsee regressions. Inherited upstream Actions stay disabled; local validation and the main RoomQuest SQL CI
cover this coordinated release. PR #289 is our separate “Fix Three Event Bugs” work, not attributed
to Awet.

## Mapsee catalog extension (October 27, 2026)

`mapsee_sources.json` pins 2,632 positively identified US candidates from
`tophe112-source/mapsee-aggregator@aa7ebd98bc43681e04aa1202e4aae7a696001813`.
`scripts/mapsee_catalog.py` builds the factual manifest; `catalogs/` contains the
complete international/US/exclusion inventory and count summary. Mapsee's MIT
notice is retained at `docs/third-party/mapsee-MIT-LICENSE.txt`; it does not license
publisher descriptions or images. None are staged or published here.

`mapsee_adapter.py` reuses Udell extraction libraries and the same source claim,
metadata staging, authenticated scheduling and shared Geocodio gateway. The
original 400-source table is unchanged; the main repository's private, pinned
Mapsee eligibility explicitly extends the queue. No source ID, URL or address
comes from a public request. New sources use an honest agent, robots/delay checks,
public-DNS validation, bounded redirects/bodies/pages/recurrences and source/staging
deadlines. Valid empty, access/fetch, time/recurrence and unsupported-format failures
remain distinct. Only real publisher/event facts and original links are retained.

The existing five collector slots run every five minutes, at most 15 sources each;
claims still lock at most four actual source leases. Python concurrency remains
three and the outer deadline 48 seconds. Geocoding retains its separate one-minute
Cron and unchanged shared quota. The production source registry, collection and
publication evidence are recorded in `RoomQuestGame/docs/mapsee-rollout.md`; a
committed catalog or local test is not evidence that those feeds work in production.


Mapsee scheduling carries the remaining job deadline into fetch/staging, permits
one short retry for a publisher lease cooldown, and retains the 15-source/three-worker
cap. The catalog priority metadata distinguishes 17 Raleigh/Wake/Durham sources and
30 Richmond/Petersburg sources; Richmond District in San Francisco remains broader
US coverage. The combined local suite passes 163 tests plus ten subtests.

## Parks search-demand cutover (November 2, 2026)

Madison County and Nebraska use the shared WordPress JSON route and normal demand claim. No new cron or city collector is added. The worker propagates its deadline; these two sources require published, visible, physical, timed listings and retain publisher timezones and addresses. Database migration 20261102095858 owns coverage routing, stable JSON identities, cached geocoding and durable publication continuation. Deploy this collector before the database registration and final Edge-default cutover. Verify with normal area searches, never manually seeded previews/events. Local WordPress/Mapsee/preview suites: 35 tests and 10 subtests pass.

## Temporary database failures (November 2, 2026)

Staging transactions contain at most 20 events. Socket/OSError failures from Supabase RPCs report database_unavailable; partial snapshots never report completion or publish. Existing source, robots, parser and venue validation remain in place.

Companion RoomQuestGame migration 20261102145352 makes database_unavailable, staging_deadline and collector_not_configured retryable with 1–15 minute backoff under existing area/validation interest. It preserves feed approval and previous data, and keeps the finish call from shortening backoff. The collector change alone does not prevent database disposition holds until that migration is deployed through GitHub. Sixth & I has a narrowly reviewed, normal-search recovery in that migration; no collector code resets source holds.

Local validation: 139 tests and 25 subtests pass, including multi-batch completion, partial failures, transport classification and category ticket completion. GitHub validation and production deployment verification are separate release steps.

## ChamberMate demand adapter (November 3, 2026)

`chambermate.py` adds ChamberMate's public JSON calendar to the existing
`chambermate` category-demand lane and shared factual intake. The Clarksville
pilot uses one bounded request, explicit UTC overlap dates, complete-snapshot
counts, source-bound event IDs, individual publisher category labels, and actual
event addresses. Online/phone records stay unlocated; physical venue review,
cached/shared geocoding, publication, and classification remain downstream.
There is no new timer or per-event detail crawl. See [CHAMBERMATE.md](CHAMBERMATE.md)
for source registration, the public contract, limits, and focused tests.





## Holly Hill and surrounding South Carolina towns

The complete November 8 intake batch is documented in
[`docs/holly-hill-source-batch.md`](../docs/holly-hill-source-batch.md), with the
full inventory in `docs/evidence/holly_hill_batch_20261108.json`.
`holly_hill_sources.py` binds twelve exact publisher configurations to the
existing guarded fetch, staging, geocoder, classifier and media contracts.
Existing regional MapSee sources retain their source keys and operator holds.
Run `python scripts/capture_holly_hill_batch.py --output /tmp/holly-hill-audit.json`
for the bounded read-only batch audit; this does not create demand or write events.
