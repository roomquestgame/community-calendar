# EventQuest public collector expansion — Batch 01 / 10 sources

Date: **2026-11-18**. Approved scope: **at most ten independent candidate publishers per canary**. The exact machine-readable source list, evidence URLs and outstanding gate states are in [Batch 01 JSON](public-source-canary-batch-01-20261118.json).

**This is a verified research/sample checkpoint, not an import or deployment receipt.** We have not activated any of the ten publishers, approved photos, or written events. All ten require source-specific worker/rights/venue tests before activation. No extra Postgres migration, PG17 squash work, cron or category backfill reset.

## Source-by-source research checkpoint

| # | Candidate | What was actually observed | Status / next test |
|---|---|---|---|
| 1 | King County Library System, WA (BiblioCommons) | Official events listing; source detail for *StoryWalk at MacFarland Park* shows through Nov. 24, event-specific place, real full narrative | Source gateway API not reachable through public web probe; test via bounded original publisher transport, preserve offsite park address and all-day rule |
| 2 | Central Rappahannock Regional Library, VA (BiblioCommons) | Publisher listing and a detailed hybrid teen-program page, with event categories | Recheck a truly future event from gateway; confirm branch address and hybrid physical/virtual semantics |
| 3 | Palm Beach County Library System, FL (BiblioCommons) | Official event listing with branch, description and category labels, over 2,000 listings at the time | Verify live gateway page, completeness, venue address/coordinates, real event image policy |
| 4 | Fulton County Library System, GA (BiblioCommons) | Indexed events/branches are visible, but direct browser page displayed a JavaScript/bot-verification screen | Access hold; respect challenge and publisher robots. Do not bypass. Alternative publisher-permitted feed if offered |
| 5 | Charlotte Mecklenburg Library, NC | Official announcement on Oct. 22 says event calendar moves from BiblioCommons to **Communico on Nov. 19** | Cutover hold. Discover the actual new Communico endpoint after change, not the historical Biblio endpoint |
| 6 | Currituck Chamber, NC (ChamberMate lead) | Official chamber website advertises ChamberMate calendar; independent public site establishes region/publisher | Exact `getEventsInfo` endpoint and a complete public event response remain unverified. No guessed tenant filter or credentials |
| 7 | Grants Pass & Josephine County Chamber, OR | Public September 2026 ChamberMate conversion announcement | Hold exact tenant/API; do not synthesize ChamberMate URL from main chamber domain |
| 8 | Mountain Home Area Chamber, AR (**HTML**, not ChamberMate) | Publisher's own Nov. 20 *A SHERLOCK CAROL* page includes 7 PM, Twin Lakes Playhouse, street and a complete description; website credits VisionAmp | Plausible source-specific HTML parser, **not** ChamberMate; verify ZIP, timezone, more dates, individual photo evidence and permissions |
| 9 | Fairfax County Government Events, VA (Drupal) | Official events view exists; Mapsee has page/venue mapping research | Dynamic content not present in static fetch, so needs actual Drupal FullCalendar payload + live venue/page parity |
| 10 | OC Parks, CA (Drupal) | Official future-event calendar exists; Mapsee has park-venue records | Source-specific parser, per-event start location vs park headquarters, categories and event photo rights need validation |

The three Biblio detail pages are publisher **HTML evidence**; they do *not* establish the gateway response, event count through EventQuest, or source image reuse rights.

## Independent operational controls and shared rules

The existing database shows why one universal success assumption would be wrong:

| Existing Biblio source | Future staged rows at audit | Description length ≥80 (all staged) | Image candidates (all staged) | Stage location |
|---|---:|---:|---:|---|
| Boston Public Library | 162 | 306/306 | 0/306 | 306/306 native or reviewed points |
| Ocean City Free Public Library | 52 | 61/61 | 61/61 | 61/61 native or reviewed points |
| Omaha Public Library | 207 | 258/263 | 0/263 | 0/263 points, **263 held** |

Description length is **not** verification of complete publisher text; compare it to exact event-detail/source facts. Image candidates are not licensed or checked for bytes by their presence. Boston's zero-image source can display normal fallback; Omaha's venue holds must not be bypassed with fake pins.

For each of the ten, the supported flow is: original publisher endpoint → bounded publisher/robots probe → **full future event occurrence** (start/end/timezone/recurrence, attendance mode) → **complete source description parity** → exact event-owned venue/street → existing venue/address/Geocodio cache → shared categories/audience/holiday overlay → original publisher image candidate check (matching image, HTTP response, bytes/MIME, rights) or safe fallback → cross-source dedupe → normal protected `external_events` writer → verified Home/Events/Map card + image/description parity. No separate feed or altered current workers.

Automatic promotion cannot occur solely because the page is readable or source code exists. If a full page lacks a description, keep the true publisher omission; don't invent text. If a valid event has no licensed image, publish only after other checks pass and use the ordinary fallback. If a future physical event lacks a confirmed event venue, hold it for review.

## How to check the batch (offline, zero production writes)

```sh
node docs/tools/audit-public-source-canary.mjs docs/public-source-canary-batch-01-20261118.json
node --test tests/audit-public-source-canary.test.mjs
```

The audit checker enforces **1–10 unique, numbered HTTPS sources**, independent factual gates and the stronger three-part event-image gate. It reports readiness only when all real evidence has been reviewed; actual public visibility requires a separate source-registration/publication receipt. It performs no HTTP requests.

## Next bounded implementation slice

1. Use the **existing approved** Biblio source adapters as references; test one King County, one Central Rappahannock and one Palm Beach publisher-owned future event per source, with full description, source venue, categories, image candidate and stable ID. Keep dense pagination within the existing worker's time/record budget.
2. Test Currituck's actual public ChamberMate feed with the existing Clarksville adapter; require exact response completeness and proper per-event time/venue/description/photo evidence before adding the tenant. Hold unknown Grants Pass tenancy.
3. For Mountain Home, test the official event list and one detail page against a dedicated HTML sample, not a fabricated ChamberMate API. No publisher logo masquerading as event image.
4. Keep Charlotte, Fulton and custom Drupal formats on their explicit holds until publisher/format evidence improves. **Do not widen beyond these ten until each source has a recorded disposition** (released with receipts, held with reason, or rejected).

The separate existing Localist UCSB `request_failed` and existing paused NYC Permitted Events `timezone_unresolved` remain **repair work**, not new-source counts in this batch. Maintain existing user-visible events while their providers are repaired.

## Live and public evidence

- Publisher source pages and detail pages are linked in the JSON evidence arrays.
- The read-only live registry comparison for the preceding discovery batch is [here](public-source-leads-20261118-reconciled.json).
- Publisher terms/rights remain **unreviewed**. No new photo has been licensed, downloaded or displayed by this batch.
- Repository integration and actual deployment/publication are separate receipts. No new source, event or image is claimed production-visible here.
