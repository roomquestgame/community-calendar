# Norfolk, Richmond and Omaha/Lincoln narrative audit

Reviewed 2026-11-13. Source coverage bounds: Virginia latitude 36.4–38.1,
longitude -78–-75.5; Nebraska latitude 40.4–41.7, longitude -97.2–-95.5.
These are source cohorts, not exact city-radius search counts. Future published
and staged snapshots were inspected, then 1,467 distinct source/title samples
were evaluated with original publisher metadata and matching staging hints.
A published category was never substituted for the automatic classifier hint.

## Initial snapshot

| Market | Published | Blank descriptions | Unclassified | Staged | Blank staged |
| --- | ---: | ---: | ---: | ---: | ---: |
| Norfolk area | 975 | 583 | 604 | 1,119 | 726 |
| Richmond area | 510 | 490 | 257 | 519 | 497 |
| Omaha/Lincoln area | 1,416 | 1,093 | 772 | 1,590 | 1,163 |

These are inspection-time counts, not an accuracy score or deployment receipt.
Generic labels and missing prose overlap; an unknown event is not automatically
an incorrect classification.

## Causes and repairs

| Evidence path | Cause | Repair |
| --- | --- | --- |
| Shared ICS | Legacy path disabled DESCRIPTION and full publisher labels | Preserve occurrence narrative and full CATEGORIES without changing legacy venue/image identity |
| WordPress / JSON-LD / Squarespace | Narrative gated by source list or omitted from normalized row | Retain sanitized description/body, with Squarespace excerpt fallback |
| Omaha BiblioEvents | Nested `definition.description` and resolved event types omitted | Retain prose and type names; do not treat audience labels as activity |
| Lincoln/Gretna LocalHop | Embedded `event.description` omitted | Retain event prose, not instance query/index text |
| Richmond CFengage | Shift description used for address extraction then discarded | Keep both structured address and bounded narrative |
| Postscript, Elleinad and race JSON-LD | Description absent from output mapping | Keep source-provided narrative |
| Lynnhaven River HTML | Navigation inside content container contaminated prose | Remove adjacent-post/navigation nodes before text extraction |
| Database staging/publication | Source-specific narrative allowlists excluded new ICS and JSON routes | Allow bounded narrative for supported families after existing claim/rights checks; use identical text in insert and unchanged-input comparison |

No new detail-page fanout is introduced. Listing-only sources and records with
no upstream prose remain blank; titles are not duplicated into descriptions.
For example, the Norfolk public ICS includes some empty descriptions and some
publisher-supplied plain-text CSS. This change does not invent missing narrative.

Captured-payload parser replay (not a production repair receipt):

| Source | Accepted records | Nonblank descriptions |
| --- | ---: | ---: |
| Norfolk library ICS | 193 | 181 |
| Mechanicsville library ICS | 90 | 90 |
| Lincoln LocalHop | 282 | 282 |
| Gretna LocalHop | 53 | 53 |
| Richmond CFengage | 12 | 12 |
| Omaha BiblioEvents first API page | 98 | 98 |

The cloud runtime cannot resolve publisher hosts through the collector's DNS
preflight. Parser replays use captured public payloads; production transport,
robots checks and source eligibility remain unchanged.

## Shared taxonomy expansion

Rules use participant evidence, not geography, library audience or venue names.

| Themes / terms | Categories | Boundary |
| --- | --- | --- |
| Crafternoon, CraftsMas, bookbinding, origami, paint night, SEWcial, paper collage | Create; Learn when instruction is explicit | Exclude retail, history, exhibitions and cooking workshops |
| Dungeons & Dragons, tabletop gaming, canasta, bunco, cribbage, chess club | Hang out; Learn when instruction is explicit | Do not apply social-game fallback to competitions or lectures |
| Coffee klatch, teen hangout, senior coffee | Hang out | A beverage or venue alone is insufficient |
| Computer basics, Excel formulas, digital/adult literacy, English conversation, ASL, Hora de Cuentos | Learn; conversation groups can also Hang out | Subjects and audience labels alone are insufficient |
| STEAM Team / STEM Studio | Learn | Require concrete science/experiment participation |
| Cardio drumming, strength and stability, beginner hula | Get active; Learn for dance instruction | Exclude lectures and equipment sales |
| Weed Warriors, volunteer sewing-kit preparation | Helping + Outdoors / Create | Require the actual volunteer task |
| Farmer’s Market | Food & Drink | Exclude planning committees |
| Kitchen sweet-treat workshops | Food & Drink + Learn | Do not classify branded cooking programs as visual crafts |

The existing category schema supports these activities. Proposed future
subcategories are **Tabletop & role-playing**, **Maker & fiber arts**, and
**Digital & language skills**. They are proposals, not persisted new keys.
A genuine gap remains **Shopping & swaps** (e.g. used-book sales and toy swaps).
Do not map a sale to Learn or Helping solely because a library hosts it; the
feedback corpus records that product decision rather than forcing a label.

## Validation and release

- Collector: 2,847 tests and 71 subtests; 5 build-selection tests passed locally.
- Shared feedback: 152 cases, including 31 new positive/near-miss cases; generated
  SQL and 14 Python evaluator tests passed. This is regression coverage, not
  representative global accuracy.
- Forward migration executed against the actual live function definitions in
  PGlite. Anchor checks and the full classifier/attribute corpus passed. Other
  schema dependencies were placeholders, so this is not a full-schema rehearsal.
- `market_description_pipeline_tests.sql` adds rollback-only real staging and
  publication checks across Norfolk, Richmond, Omaha, Lincoln and ViBe, including
  invalid/oversized text, unchanged refreshes, occurrence identity and removal.
- The ready-head GitHub run must execute the complete native PostgreSQL suite.
  Deployment must then pass the standard fresh live-schema rehearsal and gates.

Version 4, manual overrides, the four-category contract, source rights, occurrence
identity, 96-hour freshness, and timestamp-only unchanged refreshes are preserved.
No global classifier sweep or search-time work is added. Existing blank records
need a successful normal source refresh after both linked changes deploy.
