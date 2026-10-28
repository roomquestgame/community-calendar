# RoomQuest community collector

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

This adapter preserves the upstream Python scrapers and supplies restricted RoomQuest ingestion and forward geocoding. Current scope is the original 400 Jon Udell community-calendar feeds. No Mapsee or additional catalog is enabled by this work.

## Server configuration

Vercel Production uses SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY and ROOMQUEST_COLLECTOR_TOKEN. The token's SHA-256 hash lives in Supabase's private preview_credentials table. Never configure a Supabase service-role key here. Existing CRON_SECRET authenticates scheduled GET requests; ROOMQUEST_PREVIEW_SECRET authenticates bounded operator POST requests. Never print, download or commit these secrets.

Geocoding additionally requires the existing Sensitive Production GEOCODIO_API_KEY and explicit FORWARD_GEOCODER_ENABLED=true. VERCEL_ENV must be production and the private database settings row must also be enabled. Public health GET reports booleans only. The key is sent only in a Geocodio Authorization header, never a URL or log.

## Ingestion

The existing five preview Cron jobs run every 15 minutes and claim up to four sources each. The worker preserves future factual title/time, publisher attribution, original link and supplied venue details. It uses the upstream recurrence expansion and supported ICS, JSON-LD, Tribe and GrowthZone adapters, with existing robots, HTTPS, DNS/IP, response-size, timeout and no-redirect safeguards. Its two existing token-scoped preview RPCs write private staging metadata and diagnostics. The separately scheduled Supabase factual publication job publishes eligible directory listings; geocoding is not a publication prerequisite. No copied publisher descriptions/images, fictional hosts or RSVPs are created.

## Forward Geocoder

Vercel Cron invokes GET /api/geocode every minute using its existing CRON_SECRET bearer convention. POST uses ROOMQUEST_PREVIEW_SECRET. Neither accepts caller-supplied addresses, URLs, IDs or a body. An unauthenticated GET is health only; unauthorized invocation cannot start work.

The Python framework uses one pyproject.toml entrypoint, api.index:handler. Its dispatcher routes geocoding to api/geocode.py and retains all existing preview slots; adding an API file or rewrite alone does not register a second Python application.

roomquest/forward_geocoder.py calls only the new community_collector_geocoder RPC for claim/reserve/submit/fail/status. Its public invoker reaches an unexposed token-validating gateway; no private function is called through public REST. The collector cannot edit settings or arbitrary events. Each unique complete US physical address has one durable private queue/cache row. New and previously imported original-cohort facts enter the same pipeline. Venue-only or incomplete addresses remain directory-visible without a map pin.

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

Photo tests: `python -m pytest tests/test_event_media.py`. Full focused suite: 67 tests plus ten
subtests. Inherited upstream Actions stay disabled; local validation and the main RoomQuest SQL CI
cover this coordinated release. PR #289 is our separate “Fix Three Event Bugs” work, not attributed
to Awet.
