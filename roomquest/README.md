# RoomQuest curator preview worker

This is a narrowly scoped integration on top of Jon Udell's preserved Python community-calendar scrapers. It previews candidate calendars and writes up to 100 **future event metadata records per source into private** `community_staged_events`, plus preview diagnostics. It never publishes events, creates native hosts, or approves publisher rights. Robots restrictions and approved server-side sources are enforced before fetching.

## Runtime configuration (Vercel production, server-side only)

- `SUPABASE_URL`: `https://drpqjuqghpjivtwznfdj.supabase.co`
- `SUPABASE_PUBLISHABLE_KEY`: the public/publishable RoomQuest project API key (not a service-role key)
- `ROOMQUEST_COLLECTOR_TOKEN`: 64 hex characters; SHA-256 hash stored only in Supabase private `rq_curator_private.preview_credentials`
- `ROOMQUEST_PREVIEW_SECRET`: 64-hex manual-operator request token
- `CRON_SECRET`: 64-hex Vercel Cron GET bearer token

**Never configure `SUPABASE_SERVICE_ROLE_KEY` in Vercel.** The Python worker can invoke exactly `community_collector_claim_previews` and `community_collector_record_preview`, gated in SQL by the scoped collector token. Admin-only RPCs and all event publication paths are separate.

## Operation

- On Admin → Data → Sources, an administrator stages a publisher and chooses **Preview**. This sets `preview_status=queued`; no fetching runs in the user browser.
- Vercel Cron invokes `GET /api/preview` **every 15 minutes** using `Authorization: Bearer <CRON_SECRET>`. Every invocation claims up to 4 due sources from Supabase, with atomic `SKIP LOCKED` locks. Claims stuck over 20 minutes can be retried.
- A separate `POST /api/preview` with `ROOMQUEST_PREVIEW_SECRET` supports bounded manual checks. No URL or source key can be provided to the endpoint.
- Plain unauthenticated `GET /api/preview` reports a minimal health summary only and does not fetch sources.
- The worker uses Udell's calendar recurrence expansion and ICS, JSON-LD, WordPress Tribe and GrowthZone parsers. It preserves future event start/end, provenance, category hints, and explicitly provided venue details, including unresolved locations for private review. Other platform adapters remain explicitly unsupported; adding a calendar catalog entry does not imply it works.
- Any retrieved event must have a true future timestamp. Venue geocoordinates come only from structured publisher event data, never from the city coverage centroid; events lacking GEO are flagged for curation.
- Preview records and staged event metadata remain private. Stage record writes use only the collector's restricted RPC token. Live public events require separately validated publisher permission and an independently deployed/scheduled municipal publication worker.

Test locally with `python -m pytest tests/`. Review Vercel usage before changing hourly frequency; automatic GitHub Actions in this fork remain disabled.

## Scale and limitations

The initial ingest target is the 400 Udell U.S. feeds, but new source catalogs may be registered in batches without requiring a predefined area. Each cron run claims no more than four sources and fetches them sequentially with publisher robots, DNS/IP, HTTPS, response-size, timeout and no-redirect safeguards. The 15-minute cadence is deliberate and can be lowered again if Vercel usage or publisher throttling requires it. This is not a general-purpose web crawler or authorization to republish publisher content. The collector currently supports four adapter types; other Mapsee configurations remain candidates until integrated. Event locations without verified coordinates stay private/held until matched to genuine event venues.\n