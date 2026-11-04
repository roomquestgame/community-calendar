## HTML worker errors and publisher pacing — November 4, 2026

[HTML_WORKERS.md](HTML_WORKERS.md) describes the coordinated two-slot HTML
release: one active publisher host at a time, source failures isolated from lane
failures, and durable crawl-delay/Retry-After metadata recorded before release.
The collector preserves failed counters and named errors; incomplete pages do
not become successful empty results. Source-error release applies only to HTML.
The release also adds strict primary-When multi-date schedule support for the
verified Natural Bridge format, with safe failing-event diagnostics.

**Deploy the additive backend contract first, then the collector.** The new
HTML-only `record_preview_v2` call preserves publisher waits atomically. Waits
that exceed a day or cannot be represented require an explicit reviewed release;
they are not silently shortened. Existing RPCs and other category outcomes
remain compatible. Bellevue Times retains its strict first-page scope.

## Bellevue Times first-page collection — November 4, 2026

The exact `bellevue_times_ne` source has a bounded first-page HTML adapter.
[BELLEVUE_TIMES.md](BELLEVUE_TIMES.md) documents occurrence timestamps, reviewed
venue addresses, per-event evidence holds, and the required backend pairing.
Ben authorized reading the accessible first page only: one request, at most
30 publisher cards, and a 30-second budget. Diagnostics explicitly label
`collection_scope=first_page` and report the publisher total and omitted later
coverage. Malformed or incomplete first-page responses still fail. Existing
MyCountyParks and Virginia dispatch and behavior remain unchanged.

The captured page reports 61 upcoming cards, while page 2 and page 3 return
HTTP 403 / Cloudflare validation. Those later pages are outside this mode's
coverage and are never requested. First-page collection may run on approved
user demand with the companion backend protection: **absence from this limited
page must not cancel or hide previously seen events that moved to later pages**.
Normal expiry/freshness remains in place. The offline result of 28 distinct
address-backed records is not evidence of a live production pull. Full-calendar
access is not required for this mode, and no challenge is bypassed.
Optional image URLs are adapter candidate metadata only; this HTML publication
path keeps public `image_url` null and does not add media promotion.

## MyCountyParks county pilot — November 3, 2026

The HTML family now has an explicit MyCountyParks dispatcher alongside Virginia
State Parks. [The MyCountyParks scraper](MYCOUNTYPARKS.md) reads county-filtered
listings and actual event street addresses with Beautiful Soup. It shares the
HTML worker and address-resolution pipeline. Four county registrations are
prepared as pending sources; source activation and production publication are
separate verification steps. Existing Virginia source behavior is preserved.

## All 46 Virginia park sources: demand-only activation

The 46 reviewed park sources are enabled in the corresponding RoomQuestGame migration after their parser changes deploy, but **collection still requires real, expiring user-area demand**. All 46 registered `feed_url` strings remain unique: the original two-letter `srchloc=XX` values for 45 parks are retained only as source identities, not relied upon for filtering. No statewide cron, poller or prefetch is introduced. Occoneechee's verified DCR park GUID stays immutable; the 45 other parks use DCR's actual public `?park=all` calendar as a **lookup-only** endpoint, read the requested park's unique GUID from the `select name/id=park` options, then fetch the exact park-specific `park=<GUID>&start=<date>&end=<date>` listing with the existing 60-day window and ten-detail-page bound. The bootstrap does not ingest statewide event details, and only one demanded park's own details can be staged. Ambiguous/unavailable/changed park picker fields abort that source rather than guessing another park or substituting arbitrary coordinates.

The source registry keeps `rights_status=unreviewed` to avoid falsely asserting agency permission; robots/HTTP access checks remain in the vetted fetch transport, which may still block some parks. Operational approval does not imply DCR permission or guarantee a successful publisher response. Offsite activities keep venue-specific addresses and shared Geocodio continuation.

**Deployment order:** pass collector Python/provider CI; merge+deploy the collector to Vercel production; then pass database PR tests, fresh-schema rehearsal and deploy the all-parks activation migration via GitHub. Finally trace a Boydton/Occoneechee search and other regional park search, checking source request, HTTP response, event counts, and user-facing results. A 403 or missing selector remains a named source error, never silent zero-event success.

## Offsite events within search radius — November 3, 2026

Ben confirmed that a 100-mile Boydton area search should include the Friends of Occoneechee State Park Monthly Meeting in Clarksville. DCR lists the Nov 4, 2026 6–7 PM meeting at Clarksville Town Hall, **321 Virginia Ave, Clarksville, VA 23927** (Chamber Room), not at the park address. The first HTML adapter had a hard skip for `Town Hall` locations, which was incorrect for a listing with a publisher-provided physical street address.

The parser now extracts a complete venue-specific street address only from the publisher's own event description. Such an offsite event is retained as **Clarksville Town Hall**, with `latitude/longitude=null` pending the existing on-demand shared address cache. It must never be pinned to the unrelated park coordinates. If an offsite listing lacks a verified full street address, only that event remains withheld, not the other park events. In-park events keep using the original approved park coordinates.

The matching RoomQuestGame migration extends the existing `wait_for_community_address` and `resume_community_addresses` checks to explicitly approved supported HTML sources while preserving existing demand, source, rights, and snapshot guards. It does not create new jobs, a second geocoding table, or automatic event imports.

Source `virginia_state_parks_oc` remains pending/unreviewed until the current collector code, the earlier official DCR calendar GUID URL correction, and this offsite fix are validated/deployed and the first live park is deliberately approved.

## Occoneechee first-pilot correction — November 3, 2026

The initial 46 registrations used `eventtype=all&srchloc=<park code>`, but official DCR park-filtered calendar links use a **long park GUID** under `park=<GUID>` plus a date window. The first vetted identifier is Occoneechee (`2013-10-18-21-10-41-00019`). The approved source URL and parser identity will be kept in sync through separate PRs; the parser appends a 60-day `start`/`end` window at request time. Other parks remain **pending** and will not be collected until their official identifiers, usage terms, and parser results are validated.

The first upcoming meeting is off-site at Clarksville Town Hall. An unverified offsite location is now skipped per event instead of failing the entire source, while unexpected parse or transport errors still fail the snapshot rather than silently removing previously published events. The existing reviewed park address and pin are used for actual in-park activities, not offsite meetings.

**Do not activate the pilot yet:** its source is pending/unreviewed, and the live DCR HTTP/robots response and first complete staging/publishing cycle have not yet been verified. The HTML worker path remains `/api/html-demand`, separate from other collector routes.

# HTML Collector — Virginia State Parks pilot (November 2, 2026)

## Scope and isolation

- **Independent production Vercel route**: `POST /api/html-demand` -> `api/html_demand.py`, its own function in `vercel.json`. ICS, WordPress, JSON-LD, Squarespace and other collectors continue through `/api/category-demand` and their original category lanes.
- **Independent database work lane**: `community_worker_slots.category='html'`, one slot, with the same one-use database-issued ticket claim/finish protocol. The HTML lane has no timer or bulk statewide scan. Only requested/approved source records can dispatch.
- **First HTML adapter**: `roomquest/virginia_state_parks.py`. It uses Beautiful Soup on official `www.dcr.virginia.gov` HTML only, and `roomquest/virginia_state_parks_catalog.json` contains the 46 owner-reviewed park identities and coordinates.
- **Common downstream publishing remains shared**: source approval, staging, classification, idempotent upserts and `external_events`. New HTML events are correctly labeled `provider='html'` and carry `facts_only_html` provenance, not `ical`.
- **Source-scoped data, not a new geocoder table**: park/address/coordinate facts are also imported to the existing reviewed venue store and normalized-address cache through the separate app/backend migration.

## Collection behavior

- A specific park source is identified by `virginia_state_parks_<two-letter-code>`, a registered official DCR calendar URL, and `kind='html', platform_adapter='html'`.
- The collector finds real event links on the park's filtered statewide calendar page, limits itself to at most ten matching detail pages, and rejects unvetted URLs/off-domain redirects.
- It preserves exact event IDs, the official source URL, eastern start/end instants and local time zone. Description is factual source text; `Program Location` becomes `Meeting Location` within the description, while the park's reviewed street address and coordinates are used for the map.
- A clearly off-site venue without its own resolved address is held rather than incorrectly pinned to the state park. No publisher images or fabricated sessions are imported.
- Existing `fetch_publisher` provides SSRF protection, TLS verification, robots checks, response size limits, request deadlines, redirect limits and pacing. The new adapter additionally pins DCR to its own official hostname.

## Launch gates

1. Merge/deploy the Python collector project first. No active HTML feeds yet.
2. Merge the RoomQuestGame DB PR after green native SQL + fresh-schema rehearsal, and run its **manual** Database deploy workflow.
3. The database migration installs 46 reviewed park locations, 46 **pending**, **unreviewed** DCR source registrations, geographic demand seeds, the HTML worker slot, independent route dispatch and HTML-only description persistence. Sources **cannot auto-collect** at this stage.
4. Confirm live preview from Occoneechee or one selected park, verify source terms/robots, and approve only the tested park through a reviewed release.
5. Run a genuine Mecklenburg/Clarksville search and trace DCR calendar -> HTML worker -> stage -> venue coordinates -> correctly labeled published event; compare title, dates, description, errors and duplicate behavior before enabling other parks.

## What is known vs unverified

Ben's Windows standalone Beautiful Soup tests verified one complete structured event and later 100 candidate links; a ten-event sample returned 6 complete records, 1 address omission and 3 redirects. Those tests are evidence that server-rendered HTML is accessible, **not** proof that this new deployed adapter, source filtering or publication path works end-to-end. CI fixtures test the safe shape without contacting DCR. HTML sources must stay pending until a real authorized pilot passes.

The implementation is hosted in the existing community-calendar Vercel **project** but has its **own route and database worker lane**; it does not need a separate Vercel account or database.
