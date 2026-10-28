# RoomQuest community collector

This adapter preserves the upstream Python scrapers and supplies restricted RoomQuest ingestion and forward geocoding. Current scope is the original 400 Jon Udell community-calendar feeds. No Mapsee or additional catalog is enabled by this work.

## Server configuration

Vercel Production uses SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY and ROOMQUEST_COLLECTOR_TOKEN. The token's SHA-256 hash lives in Supabase's private preview_credentials table. Never configure a Supabase service-role key here. Existing CRON_SECRET authenticates scheduled GET requests; ROOMQUEST_PREVIEW_SECRET authenticates bounded operator POST requests. Never print, download or commit these secrets.

Geocoding additionally requires the existing Sensitive Production GEOCODIO_API_KEY and explicit FORWARD_GEOCODER_ENABLED=true. VERCEL_ENV must be production and the private database settings row must also be enabled. Public health GET reports booleans only. The key is sent only in a Geocodio Authorization header, never a URL or log.

## Ingestion

The existing five preview Cron jobs run every 15 minutes and claim up to four sources each. The worker preserves future factual title/time, publisher attribution, original link and supplied venue details. It uses the upstream recurrence expansion and supported ICS, JSON-LD, Tribe and GrowthZone adapters, with existing robots, HTTPS, DNS/IP, response-size, timeout and no-redirect safeguards. Its two existing token-scoped preview RPCs write private staging metadata and diagnostics. The separately scheduled Supabase factual publication job publishes eligible directory listings; geocoding is not a publication prerequisite. No copied publisher descriptions/images, fictional hosts or RSVPs are created.

## Forward Geocoder

Vercel Cron invokes GET /api/geocode every five minutes using its existing CRON_SECRET bearer convention. POST uses ROOMQUEST_PREVIEW_SECRET. Neither accepts caller-supplied addresses, URLs, IDs or a body. An unauthenticated GET is health only; unauthorized invocation cannot start work.

roomquest/forward_geocoder.py calls only the new community_collector_geocoder RPC for claim/reserve/submit/fail/status. Its public invoker reaches an unexposed token-validating gateway; no private function is called through public REST. The collector cannot edit settings or arbitrary events. Each unique complete US physical address has one durable private queue/cache row. New and previously imported original-cohort facts enter the same pipeline. Venue-only or incomplete addresses remain directory-visible without a map pin.

The worker claims one address at a time, reserves a quota slot before every outbound request, uses Geocodio /v2/geocode with an eight-second timeout, and processes at most ten requests within a 45-second budget inside the 60-second Vercel function limit. It never retries HTTP automatically. Durable transient retries back off and stop after five attempts; ambiguous matches stop, 429 pauses until the next UTC day, and provider-auth errors pause for an hour. A crash leaves an expiring lease and a consumed reservation.

The database serializes reservations across all workers and enforces both a server UTC-day and rolling 25-hour-plus-30-second cap of at most 2,300 attempted requests, including failures and retries. Quota exhaustion stops processing automatically. No paid-overage, batch-geocoding or field-append feature is activated. Rooftop/point matches require score >=0.9, exact event street/city/state and US country evidence, valid coordinates and no conflicting close candidate. Publisher headquarters/region never substitutes for an event venue. Cached verified coordinates and provider evidence are retained for reuse, written to existing external_events.location, and preserved by the factual-refresh trigger. Native events and other providers are excluded.

## Release and checks

Deploy RoomQuest PR #285 through its protected database workflow first; it reconciles the explicitly audited history records and applies the disabled geocoder migration without bypassing schema gates. Verify the private cohort is exactly 400. Start with database daily_cap=3 and enabled=true, then deploy this collector with the Production switch enabled. Confirm key presence through metadata/health, actual Cron requests, ledger/provider evidence, correct geographic discovery and refresh persistence before raising the database cap to 2300. See RoomQuestGame/docs/udell-geocoding-rollout.md for the complete runbook. A READY deployment alone is not processing evidence.

Run focused tests locally with python -m pytest tests/test_roomquest* tests/test_forward_geocoder.py. The main repository also runs rollback-only SQL authorization, address/cache, discovery, refresh/provider-regression and concurrent quota tests. Review actual Vercel usage when changing schedule frequency. Upstream GitHub Actions remain disabled, and the ignored-build command skips nonproduction builds. Health and batch responses expose aggregate counters only; operational queue/usage status requires the restricted collector token or a privileged database operator.
