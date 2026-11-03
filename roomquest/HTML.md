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
