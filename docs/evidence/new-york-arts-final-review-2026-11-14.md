# New York arts, family, makers and library — final batch review

Reviewed 2026-11-14T23:14:59.578529+00:00. This batch adds five previously unregistered source identities. A read-only production alias query returned no matching source or public event ownership. No already-published source is reenrolled.

## Capture and implementation

| Publisher / source key | Native format | Accepted rows | Full description length |
|---|---|---:|---:|
| New York Transit Museum / `ny_transit_museum_ny` | TEC facts + full detail HTML | 17 | 624–4119 characters |
| Brooklyn Children’s Museum / `brooklyn_childrens_museum_ny` | Events Manager ICS; rolling30days | 24 | 295–677 characters |
| Flushing Town Hall / `flushing_town_hall_ny` | ARTdynamix HTML, native performance tables | 12 | 362–2290 characters |
| MakerSpace NYC / `makerspace_nyc_ny` | Official class links + public Eventbrite Next.js content | 8 | 1814–3168 characters |
| Brooklyn Public Library — BPL Presents / `brooklyn_public_library_presents_ny` | BPL Presents Drupal listing + full native detail HTML | 12 | 1113–6275 characters |

All 73 accepted rows have nonblank, complete descriptions below12,001 characters, full New York postal street addresses, explicit reviewed points and exact event URLs. There are 17 unique streets. Four station-tour rows visibly say “approximate meeting point; check ticket instructions”; the source narratives remain intact. Every accepted description has a SHA256 production-verification baseline in the capture.

The replay uses actual collector code and the shared production `record` normalizer. Public research requests used the worker User-Agent and permitted robots paths, with10-second spacing for Transit/Flushing and the advertised publisher delays elsewhere. Local guarded transport cannot resolve public DNS in this sandbox, so these receipts demonstrate ordinary public capture and actual normalization replay, not a completed production release. Production E2E remains the root batch rollout gate.

## Complete descriptions and schedules

### New York Transit Museum

TEC event facts have blank descriptions; all eligible public pages are hydrated from every full narrative column and full accordion policy body. Five holiday rides use the publisher-named 2 Av–Houston boarding station and an official MTA entrance point. Four Grand Central/Penn walks use explicit approximate-meeting labels and verified station addresses. Two route-only walks lack a sufficiently bounded meeting venue and are held; seven members-only City Hall tours and one virtual program are excluded.

### Brooklyn Children’s Museum

Native Events Manager ICS provides full descriptions, explicit dated occurrences, and attachment images. The 50-row publisher feed ignores limit=200. A rolling 30-day window is enforced, with a horizon guard that fails if a full feed stops before the requested window. Member-only and closure notices are excluded. Ordinary Play at BCM programs retain their complete guided studio/makerspace session descriptions; no recurrence dates are invented.

### Flushing Town Hall

Native ARTdynamix detail #about is complete; the duplicated mobile block is excluded. Native performance tables supply exact start clocks. Six off-site named venues retain their own reviewed streets/points. Stone’s Throw has explicitly published Tue–Sun noon–6 exhibition hours through Nov15 and a separate Nov14 6:30 panel. One Zoom office-hours item is excluded.

### MakerSpace NYC

Official MakerSpace classes page links its own Eventbrite organizer18615337552/organization61731221749. Public Next.js HTML carries full text modules and native venue coordinates. Three multi-date parent events are expanded only from explicit dated session lines within the native series endpoints; no multi-month continuous event is published. Seven past/completed classes are excluded. Native sales state on_sale is used for evidence; SEO Offer availability can be stale and is not treated as an authoritative cancellation.

### Brooklyn Public Library — BPL Presents

Narrow BPL Presents series, not a claim of the entire citywide branch calendar. Ordinary Drupal HTML exposes 15 dated cards; 12 are within the rolling60-day window. Complete first content column preserves all biographies and program text; the Add-to-Calendar description is explicitly truncated and is never used. Each accepted native branch address/ZIP is checked against its exact branch identity, including the Dweck room and Arts & Culture Second Floor. Four reviewed NYC PAD points are attached. Listing, canonical URL, title, date/time, series tags and branch identity are verified; pagination changes fail closed.

## Checkpoint and access boundary

Transit, Flushing, MakerSpace and BPL Presents use the existing durable checkpoint wire shape: version1, UTC `started_at`, local date-only `window_start`, four-hour lifetime, at most200 manifest entries/events and900KB. An initial slow manifest may be saved with cursor0. Subsequent invocations hydrate details directly without repeatedly fetching the listing. Before the batch can be emitted, the full current manifest is fetched again and its hash must match; a changed manifest discards every hydrated row and restarts. A completed but unverified cursor emits no rows. Once verified, retries are deterministic without HTTP.

A simulated cold10-second publisher delay within36-second invocations advances a three-item manifest through `(cursor1, incomplete)`, `(cursor3, incomplete)` and `(cursor3, complete)`. The final invocation verifies the manifest. The root is adding a narrow Transit host delay floor because Transit places its10-second directive before the User-agent group; no robots permissions or identities are relaxed.

## Reviewed locations

| Source | Venue | Full address | Latitude, longitude |
|---|---|---|---|
| New York Transit Museum | New York Transit Museum, Brooklyn | 99 Schermerhorn Street, Brooklyn, NY 11201 | 40.6903327, -73.9896449 |
| New York Transit Museum | 2 Av–Houston St station (uptown F boarding) | Second Avenue & East Houston Street, New York, NY 10003 | 40.7239689, -73.9912799 |
| New York Transit Museum | Grand Central Terminal (approximate meeting point; check ticket instructions) | 89 East 42nd Street, New York, NY 10017 | 40.752732, -73.977218 |
| New York Transit Museum | Penn Station / Moynihan Train Hall (approximate meeting point; check ticket instructions) | 351 West 31st Street, New York, NY 10001 | 40.751538, -73.995854 |
| Brooklyn Children’s Museum | Brooklyn Children's Museum | 145 Brooklyn Avenue, Brooklyn, NY 11213 | 40.674511, -73.943896 |
| Flushing Town Hall | Lorimoto Gallery | 1623 Hancock Street, Queens, NY 11385 | 40.697943, -73.906408 |
| Flushing Town Hall | Flushing Town Hall | 137-35 Northern Boulevard, Flushing, NY 11354 | 40.763883, -73.830072 |
| Flushing Town Hall | Lewis Latimer House | 34-41 137th Street, Flushing, NY 11354 | 40.766757, -73.829338 |
| Flushing Town Hall | Queens Community House | 108-25 62nd Drive, Forest Hills, NY 11375 | 40.736304, -73.850091 |
| Flushing Town Hall | War Veterans Post 1979 | 263-15 Union Turnpike, Glen Oaks, NY 11004 | 40.748863, -73.70922 |
| Flushing Town Hall | Queens Boulevard Extended Care Lobby | 61-11 Queens Boulevard, Woodside, NY 11377 | 40.741704, -73.903008 |
| Flushing Town Hall | Terraza 7 | 40-19 Gleane Street, Elmhurst, NY 11373 | 40.747603, -73.881805 |
| MakerSpace NYC | MakerSpace NYC — Brooklyn Army Terminal | 140 58th Street Building B Unit 1C, Brooklyn, NY 11220 | 40.6455001, -74.0239072 |
| MakerSpace NYC | MakerSpace NYC — Brooklyn Army Terminal | 140 58th Street Building B Unit 1C, Brooklyn, NY 11220 | 40.6451278, -74.02420630000002 |
| Brooklyn Public Library — BPL Presents | Central Library, Dweck Center | 10 Grand Army Plaza, Brooklyn, NY 11238 | 40.6724, -73.96809 |
| Brooklyn Public Library — BPL Presents | Library for Arts & Culture | 10 Lafayette Avenue Second Floor, Brooklyn, NY 11217 | 40.686172, -73.978456 |
| Brooklyn Public Library — BPL Presents | Center for Brooklyn History | 128 Pierrepont Street, Brooklyn, NY 11201 | 40.694798, -73.992413 |
| Brooklyn Public Library — BPL Presents | Brooklyn Heights Library | 286 Cadman Plaza West, Brooklyn, NY 11201 | 40.695753, -73.991452 |

Exact numbered streets are paired with reviewed NYC Planning PAD features (house number, street, borough and postal code), or the publisher’s own event point. The two MakerSpace native coordinate variants refer to the same reviewed building/unit and are retained. The holiday train’s Second Avenue/East Houston Street location uses the official MTA F14 station entrance; it identifies a boarding entrance, not a moving train’s position. Station tours use verified Grand Central and Moynihan entrance addresses as visibly approximate meeting locations, because exact tour meeting instructions are not provided by the public event page.

## Concrete remaining holds

- **New York Transit Museum:** Native venue is Off-Site and prose describes a route, not a bounded start venue. No named station/entrance can responsibly be selected from the route endpoints.
- **Greenlight Bookstore:** Production B2 collection returned publisher_http_403 at 2026-11-14 23:05 UTC and source was safely paused. Earlier ordinary research capture succeeds from a different network; it is not evidence that production access works. Do not re-enable solely to retry or change identity.
- **Queens Museum:** Most recent ordinary-access robots check returned HTTP202 (not usable robots status). Remains an access hold; no proxy identity or path bypass attempted.
- **National Lighthouse Museum:** Previously audited permitted TEC feed contained zero upcoming occurrences. No future dates invented.
- **Alice Austen House:** Previously audited event feed was empty; no dated future occurrence confirmed.
- **New York Public Library:** Robots allowed200 but ordinary calendar returned only a212-byte JavaScript/challenge shell, no actual event content. No challenge bypass attempted.
- **Queens Public Library:** Robots request redirected to connect.queenslibrary.org and returned403; no further event fetch or alternate-identity bypass attempted.

The live Greenlight403 is a production access failure after a successful local research capture. It must remain paused unless ordinary approved production access is restored. NYPL/QPL/Queens Museum are access holds, not omitted engineering work. Lighthouse/Alice Austen have no confirmed future dated feed rows in the existing audit. Working published sources remain excluded from this batch.

## Validation and handoff

- `python -m unittest tests.test_new_york_arts_final tests.test_new_york_arts_remaining tests.test_new_york_arts -q`:56 tests passed, including23 focused tests for this module.
- Tests cover exact source/URL profiles, long-body preservation, no excerpt substitution, missing/oversize rejection, off-site/branch address binding, explicit dated series, incomplete publication protection, fresh final-manifest reset, cold pacing, UTC expiry, checkpoint tampering and all publisher category evidence.
- Code is limited to `roomquest/new_york_arts_final.py` and `tests/test_new_york_arts_final.py`. B1/B2 files and classifier rules are unchanged.
- Machine capture: `new-york-arts-final-capture-2026-11-14.json`. Research/access/PAD receipts: `new-york-arts-final-research-2026-11-14.json`.

Prior classifier audits remain separate and honest: B1/B2 reviewed samples found classification misses. This release neither changes nor conceals those results.
