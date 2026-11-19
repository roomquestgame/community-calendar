# EventQuest Lowcountry seventh continuation — November 19, 2026 14:42 EST

## Execution
This is active discovery/validation; **0 newly deployed feeds** (target 20); **0 verified release-ready**, **17 held distinct unregistered publisher candidates** after adding three original first-party calendars. No unauthorized changes to production or pending PostgreSQL-17 migration squash. This checkpoint compared the prior run's queue, collector PR #339 and current READY production collector deployment at https://vercel.com/room-quest-game/roomquest-community-collector/DyRQ2iziUFMx5jn1fwnZpZxUkCXu (commit d4ed71c4a7274c473fe3950d2529c5759a200513; later unrelated Santa Cruz work; collector contains Palmetto Bluff released PR #339), the currently applied migration ledger (latest observed 20261130010000, unrelated EVE145); no new Lowcountry source installed.

Read-only production exact-source IDs: 5803–5807, 5813–5817, 5873, 5879, 5886, 5889, 5894. 15 approved/preview-complete sources; source stage-future total 326; 324 published source-associated cards (status=scheduled, none hidden); 317 future-visible. All 324 published rows have GEO and numbered street prefix and none use category=other; provider_event_id+starts_at unique within each source. 10 of 324 descriptions are under 40 chars (1 Beaufort, 1 Bluffton, 2 HHI, 2 Lobeco, 4 St Helena). Do not assert all descriptions >=40 chars or all 324 are future.

## Discovery across all nine categories

| Lane | First-party evidence, decision |
| --- | --- |
| Nightlife and Social | Comedy Magic Cabaret SeatEngine publisher still held; production FindLocal already has 33 at 843 William Hilton Pkwy / 29 future: do not double-publish. Sea Pines seasonal entertainment and Arts Center performance shows under new holds. |
| Arts, Culture and Education | New official Arts Center first-party program at https://www.artshhi.com/performances, Cheyenne Jackson separately timed 4:00 and 7:30 PM Dec15 https://www.artshhi.com/presenting-series/cheyenne-jackson, plus Annie season Dec2–Jan3 with no verified individual showtimes. Existing SOBA, Art League and Coastal Discovery holds persist. |
| Outdoor and Active | New official Hunting Island State Park https://southcarolinaparks.com/hunting-island/programs-and-events has December nature programs. Meeting places Nature Center, Lighthouse and Marsh Boardwalk differ; do not pin to statewide 2555 Sea Island Parkway park entrance. Palmetto Bluff Conservancy already live. |
| Food and Drink | Existing Greenhouse, Southern Barrel, Roasting Room cover this lane. Chamber social/coffee programs already held; avoid counting existing publishers or locations again. |
| Family and Kids | New Sea Pines official publisher Dec19 Polar Pines Express https://www.seapines.com/experiences/events/polar-pines-express-holiday-wagon-ride at Heritage Farm 185 Greenwood Drive; Hunting Island Crafting with Nature for 4+ first-party https://southcarolinaparks.com/products/10007698. Need exact event meeting point, not merely park resort address. |
| Sports and Fitness | Hunting Island beach yoga/hike and prior Palmetto Running Company are promising, but separate start-site GEO and eligibility still unresolved. USCB student-access risk persists. |
| Markets, Makers and Shopping | Palmetto Bluff pop-up already live; SOBA holiday market and Bluffton Farm & Flea still held. Do not substitute third-party recurring market listings for publisher originals. |
| Gaming and Hobbies | No NEW independent publisher meets public-access, event-specific date, original URL and numbered venue GEO. Library chess/Mahjong already included; Comedy Magic is not a new gaming feed. |
| Civic, Volunteering and Community | Greater Bluffton Chamber original Dec3 detail https://blufftonchamberofcommerce.org/events/details/get-to-know-your-chamber-membership-benefits-overview-december-2026-21153 establishes public/future-member eligibility, original full narrative, 8:30–10:00 and The Cove 97 Progressive St. SC Commerce https://properties.zoomprospector.com/sccommerce/property/97-Progressive-Street-Bluffton-South-Carolina/F80F63FB-AB81-4307-ADF1-1A63AB9FC7C1 gives location 32.2733 -80.9186; alternative property data gives 32.2732 -80.9185; still need exact Cove unit verification and robots/collector. Port Royal and bounded Beaufort government monthly listing still held. |

## Release blockers and next actions
1. Verify publisher robots/terms for each candidate using a collector robots-safe live canary; no bypass, no long unbounded pages.
2. Get independently reviewed exact event-venue meeting-location GEO for Sea Pines Heritage Farm, Arts Center, and Hunting Island sublocations; if not precise, stage/hold only.
3. Chamber-owned ChamberMaster events are strongest parser candidate, but split per-event addresses and perform exact venue + duplicate verification (no generic Chamber office geo).
4. Review FindLocal coverage and dedup before publishing Comedy Magic Cabaret copies; official publisher descriptions may improve existing cards without creating duplicates.
5. Implement bounded first-party adapters + regression tests for each validated publisher, merge only tested code, verify Vercel READY exact included SHA; enroll with ONE forward-only migration after ledger latest via protected db-deploy.yml, never direct Supabase writes. Deploy ANY number ready below 20; no manufactured readiness this cycle.
6. Investigate 10 short library descriptions without changing protected source and unrelated ingestion jobs.

## Full source queue
https://github.com/roomquestgame/community-calendar/blob/main/docs/lowcountry-source-queue-20261119.json
