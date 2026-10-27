# RoomQuest curator preview worker

This is a narrowly scoped integration on top of Jon Udell's preserved Python community-calendar scrapers. It previews **candidate** event calendars and writes diagnostics to RoomQuest's private Supabase source registry. It never publishes events, creates native hosts, or approves publisher rights.

## Runtime configuration (Vercel production, server-side only)

- `SUPABASE_URL`: `https://drpqjuqghpjivtwznfdj.supabase.co`
- `SUPABASE_PUBLISHABLE_KEY`: the public/publishable RoomQuest project API key (not a service-role key)
- `ROOMQUEST_COLLECTOR_TOKEN`: 64 hex characters; SHA-256 hash stored only in Supabase private `rq_curator_private.preview_credentials`
- `ROOMQUEST_PREVIEW_SECRET`: 64-hex manual-operator request token
- `CRON_SECRET`: 64-hex Vercel Cron GET bearer token

**Never configure `SUPABASE_SERVICE_ROLE_KEY` in Vercel.** The Python worker can invoke exactly `community_collector_claim_previews` and `community_collector_record_preview`, gated in SQL by the scoped collector token. Admin-only RPCs and all event publication paths are separate.

## Operation

- On Admin → Data → Sources, an administrator stages a publisher and chooses **Preview**. This sets `preview_status=queued`; no fetching runs in the user browser.
- Vercel Cron invokes `GET /api/preview` **hourly** using `Authorization: Bearer <CRON_SECRET>`. Every invocation claims up to 4 due sources from Supabase, with atomic `SKIP LOCKED` locks. Claims stuck over 20 minutes can be retried.
- A separate `POST /api/preview` with `ROOMQUEST_PREVIEW_SECRET` supports bounded manual checks. No URL or source key can be provided to the endpoint.
- Plain unauthenticated `GET /api/preview` reports a minimal health summary only and does not fetch sources.
- The worker uses Udell's calendar recurrence expansion and ICS, JSON-LD, WordPress Tribe and GrowthZone parsers. Other platform adapters remain explicitly unsupported; adding a calendar catalog entry does not imply it works.
- Any retrieved event must have a true future timestamp. Venue geocoordinates come only from structured publisher event data, never from the city coverage centroid; events lacking GEO are flagged for curation.
- Preview records remain private. Live public events require separately validated publisher permission and an independently deployed/scheduled municipal publication worker.

Test locally with `python -m pytest tests/`. Review Vercel usage before changing hourly frequency; automatic GitHub Actions in this fork remain disabled.
