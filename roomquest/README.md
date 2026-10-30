## ChamberMaster provider — prepared, not activated (October 29, 2026)

Ben approved one separately managed ChamberMaster API provider with Orangeburg
as its first source. `/api/chambermaster` uses the existing operator/Cron secrets
and the scoped collector token; callers cannot choose URLs or source IDs. It
claims one chamber from the new protected registry gateway and stages facts
through the existing RPCs. The public XML schedule is parsed by Udell's actual
GrowthZone code; bounded event-specific iCalendar exports supply event venue
text, with matching EventID and exact start time required. No chamber-wide
coordinates, descriptions, photos, geocoder grants or native events are added.

Deploy the companion `20261030024648_chambermaster_provider_registry` migration
and validate its exact token-gated wrapper/security exception before invoking
this endpoint. The global provider and Orangeburg source begin disabled/pending;
no collection Cron is added. Admin API health shows the separately managed
provider and source controls reuse the existing Data registry. A successful
private preview is not public geographic publication. The existing community
publisher job remains paused. See [provider contract](../docs/chambermaster-provider.md).

Local focused checks: 60 passed, 10 subtests passed. The broader pre-existing
scoped-RPC test still expects five disabled preview Cron entries; this batch
does not restore them. The new registry/queue SQL passes an isolated PostgreSQL
fixture, not a full live-schema/PostGIS rehearsal. CI, merge, guarded database
release, collector deployment and live preview remain pending.

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
