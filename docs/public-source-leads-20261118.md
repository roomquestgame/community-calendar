# External public-calendar leads — audited November 18, 2026

This owner-approved discovery batch surveys GitHub/GitLab and original publisher sites for supported EventQuest feed families. It **does not activate or scrape new publishers**. The evidence manifest is `docs/public-source-leads-20261118.json`.

## Production read-only overlap
- `municipal_event_sources`: 3,881 sources; 2,968 with approved source-status (not necessarily public visible); 993 with a nonzero staged-future count; 816 successful checks in the prior seven days.
- Dedicated Localist registry: **85** registrations. All **58** hosts in public Mapsee `localist_sources.json` already exist in it. UC Santa Barbara is registered as `localist_66fbc80a958a89e3` but latest request failed, with zero successful pulls. Repair rather than duplicate.
- Three direct BiblioEvents integrations already exist: Boston Public Library, Ocean City Free Public Library and Omaha Public Library. The publicly available Mapsee BiblioCommons catalog contains 67 tenants, many unregistered.
- Clarksville ChamberMate already stages five future occurrences; four physically located future events are held for missing verified coordinates, and one virtual future event is held as remote. Its staged descriptions and photo **candidates** do not prove public photo licensing or readiness.
- Dallas Parks includes the already-registered catID=14 ICS feed plus distinct category feeds; preserve exact query selectors.

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
