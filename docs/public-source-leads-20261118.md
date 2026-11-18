# External public-calendar leads — audited November 18, 2026

This owner-approved discovery batch surveys GitHub/GitLab and original publisher sites for supported EventQuest feed families. It **does not activate or scrape new publishers**. The evidence manifest is `docs/public-source-leads-20261118.json`.

## Production read-only overlap
- `municipal_event_sources`: 3,881 sources; 2,968 with approved source-status (not necessarily public visible); 993 with a nonzero staged-future count; 816 successful checks in the prior seven days.
- Dedicated Localist registry: **85** registrations (**55 enabled/OK, 14 enabled/request_failed, 11 enabled/store_failed, 5 disabled** at readback). All **58** hosts in public Mapsee `localist_sources.json` already exist in it. UC Santa Barbara is registered as `localist_66fbc80a958a89e3` but latest request failed, with zero successful pulls. Repair rather than duplicate.
- Three direct BiblioEvents integrations already exist: Boston Public Library, Ocean City Free Public Library and Omaha Public Library. The publicly available Mapsee BiblioCommons catalog contains 67 tenants, many unregistered.
- Clarksville ChamberMate already stages five future occurrences; four physically located future events are held for missing verified coordinates, and one virtual future event is held as remote. Its staged descriptions and photo **candidates** do not prove public photo licensing or readiness.
- Dallas Parks includes the already-registered catID=14 ICS feed plus distinct category feeds; preserve exact query selectors.

## Exact live source-key reconciliation

The read-only comparison across all **3,881** municipal rows and **85** dedicated Localist rows is saved in `docs/public-source-leads-20261118-reconciled.json` (12 researched leads, 2026-11-18). Results: **4 already registered**, **4 pending exact publisher feed probes**, **2 lacking confirmed platform endpoints**, **2 requiring adapter/schema review**. All retain `auto_register: false` and `auto_publish: false`.

A newly identified existing record is `municipal_mapsee_844b6c0e0aca1771e1a1646f` (NYC Permitted Events Socrata): **paused**, `preview_error=timezone_unresolved`, zero future staged; it needs a reviewed mapping/timezone repair, not a duplicate registration. The 4 existing rows include UCSB, Boston Public Library and Dallas Parks as above.

## Reproducible offline reconciliation
`scripts/reconcile-public-source-leads.mjs` reads a manually researched lead manifest and current read-only registry JSON exports. It never opens network connections, queries a database, creates source records, executes collectors, modifies the PG17 schema, changes worker scheduling, or publishes images/events.

```sh
node scripts/reconcile-public-source-leads.mjs \
  --leads docs/public-source-leads-20261118.json \
  --registry /tmp/municipal-source-export.json \
  --registry /tmp/localist-source-export.json \
  --output /tmp/source-lead-report.json
node --test tests/reconcile-public-source-leads.test.mjs
```

The tool reconciles Localist host vs `/api/2/events`, ChamberMate exact tenant vs documented public API, BiblioCommons storefront vs gateway, and separate ICS category URL selectors. Unknown ChamberMate tenant is a **hold**, not a guessed API. Source matches are only leads; not proof of permission, useful events, or correct media.

## Source admission and description/photo parity

Each newly discovered publisher remains on **review hold** until:
1. Verify the **exact publisher URL**, public feed endpoint, current publisher terms, attribution, allowed programmatic requests and robots/crawl delays; no protected-page workaround.
2. Run the existing bounded parser on real upcoming occurrences; compare source title, **complete real description**, attendance mode, schedules, timezone, cancellation, category evidence, stable identity and original event URL. Missing descriptions must remain honest unknowns, not invented filler.
3. Verify the event **venue's own** official address or point, not the regional/publisher centroid; use existing venue/address cache and capped Geocodio. Withhold virtual/ambiguous/unlocatable physical events from geographic cards.
4. Extract publisher-event image **candidates** separately from cards. Validate matching event, HTTPS reachability, image bytes/MIME/size, and distribution **rights** using existing media workers. A URL or publisher logo does not authorize an image. No approved image => normal fallback, not suppression of valid event facts.
5. Check cross-provider duplicates, publisher permissions, recurring instances, category/holiday/audience overlays and exact live Home/Events/Map count. Preserve normal 96-hour refresh, exceptions, active jobs and stable external-event IDs. No separate public feed.
6. Only after an approved admission and deployment, confirm actual stages, public occurrences, unmodified descriptions, media permission/result, venues, and no duplicates. No claim from a READY deployment alone.

## Priority batch
1. **ChamberMate:** Currituck (official tenant portal), Grants Pass and Mountain Home AR (platform adoption/calendar evidence but no exact independently verified public API tenant). Test bounded one-tenant endpoints before source admission.
2. **BiblioCommons:** Charlotte Mecklenburg, King County and Central Rappahannock. Reuse the existing source libraries only where payload compatibility, branch coordinates, full descriptions and pagination have been proven.
3. **Drupal:** Fairfax County and Orange County Parks from Mapsee's published fullcalendar configs. Requires source-specific parser validation, not a false claim that generic HTML works.
4. **Socrata:** NYC Permitted Events needs an explicit schema mapping and rights review.
5. **Localist:** repair UCSB's failed connection; no duplicate Mapsee entries.

**This PR is research/reconciliation only.** It does not change production SQL, sources, descriptions, images or events; source and image publishing still require their existing review and evidence path.

## Publisher-site sample findings (read-only; 2026-11-18)

- **King County Library System (KCLS)**: The official [BiblioCommons events listing](https://kcls.bibliocommons.com/v2/events?page=1&types=56a93aa4fa6b611f620201d0) shows **LEGO Block Party** at **Duvall Library, November 19, 2026, 4:30–5:30 PM**, with descriptive event prose; other official [KCLS listings](https://kcls.bibliocommons.com/v2/events?page=3&types=5679e0f352c7b9de5c01213b) show **Teen Dungeons & Dragons Club**, Tukwila, November 19, 4:00–5:30 PM, and [the virtual-event filter](https://kcls.bibliocommons.com/v2/events?locations=BC_VIRTUAL) confirms virtual programs are also mixed into the platform. This verifies that useful future events and descriptive text exist on the publisher's public HTML. It does **not** establish complete gateway API payload, full-event-description parity, street mapping, image bytes/rights, publisher permission or EventQuest ingestion readiness.
- **Mountain Home Area Chamber (AR)**: The official [November 2026 event calendar](https://enjoymountainhome.com/events) lists **Teen Friday After Hours — Vikings** at Baxter County Library on November 20, and **Mountain Home Symphony Concert** on November 22 with 1600 S College Street as its listed venue. The [publisher print view](https://enjoymountainhome.com/events/print-events/) includes event-description paragraphs. This is genuine event evidence but is **not** verification of its ChamberMate JSON tenant, description/photo payload shape or publisher media rights.
- A protected raw BiblioCommons gateway request and the ChamberMate robots endpoint could **not** be independently read in this session. Do not mark the corresponding API, robots, image, or complete-description checks passed by extrapolating from web search snippets.

All observed events remain **research-only leads**, not newly staged, geocoded, categorized or published EventQuest events.
