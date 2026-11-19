# Lowcountry 10th continuation — November 19, 2026, ~18:05 EST

## Release receipt: first-party Greater Bluffton Chamber now LIVE

Read-only post-release checks of **exact previous 15 source IDs plus new 5907** found 16 approved/healthy Lowcountry sources with `preview_status=complete`. All earlier sources preserved. This feed was implemented and enrolled by overlapping approved execution after the prior checkpoint, *not* by this queue/journal PR.

- Source: `greater_bluffton_chamber_sc`, publisher official `https://blufftonchamberofcommerce.org/events/catgid/6`, municipal source ID **5907**.
- Collector [PR #372](https://github.com/roomquestgame/community-calendar/pull/372) MERGED SHA `bd3c608d5020255b3b1a38fac89174f0d95f5bb0`; [Vercel production deployment](https://vercel.com/room-quest-game/roomquest-community-collector/2C7PJY8BzxcciMpnFEchGhQdntgm) **READY at exact SHA**. Collector parser restricts to original Chamber-owned education events at an independently validated room; 24 focused tests passed as documented on collector PR.
- Database [PR #1389](https://github.com/roomquestgame/RoomQuestGame/pull/1389) MERGED SHA `2f035789ff52a328c55dba751587f3b58f7af54a`; **forward-only migration `20261203023000`** confirmed in production `supabase_migrations.schema_migrations`. DB enrollment was by the protected workflow, not manual SQL. Other migrations remain preserved.
- New source live health `ok`, preview complete, `preview_future_count=1`, `stage_future_count=1`, no preview error, latest successful source collection 2026-11-19 23:04 UTC.
- Exact public event: `bluffton_chamber:21153`, **Get to Know Your Chamber - Membership Benefits Overview - December 2026**, 2026-12-03 **08:30–10:00 EST**, original `https://blufftonchamberofcommerce.org/events/details/get-to-know-your-chamber-membership-benefits-overview-december-2026-21153`, **97 Progressive Street, Bluffton, SC 29910**, 32.272939834494 / -80.915951812245, 1,179-character full first-party narrative. One published public scheduled future-visible card; stage `include` rules passed. No unreviewed images were copied. One unique occurrence, not a source-preview-only event.
- **Data-quality flag:** stage classifies `learn` but published card unexpectedly maps to `give_back`, although event is educational and not volunteer work. Filed focused [app issue #1392](https://github.com/roomquestgame/RoomQuestGame/issues/1392). Do not restart national reclassification/overlays or modify unrelated cards.
- **No extra feed** was shipped by the queue-update work; the +1 release occurred between hour-nine and this checkpoint.

## Read-only production audit — exact 16 source IDs

`5803-5807`, `5813-5817`, `5873`, `5879`, `5886`, `5889`, `5894`, `5907`.

| Metric | Verified |
| --- | ---: |
| Approved, preview-complete feeds | 16 |
| Source-reported staged-future records | 327 |
| Scheduled source-associated external public cards | **325** |
| Cards with starts_at > NOW() | 309 |
| New actual Chamber published cards | 1 |
| Missing public GEO / numbered street / Other category | 0 / 0 / 0 |
| Older library public cards with descriptions <40 chars | 10 |
| Full validated-but-not-enrolled queue | 0 |
| Unverified publisher HOLD queue | 19 |

Total cards are source-associated, not necessarily globally unique. The stage 327 vs 325 difference is not a count of unpublished new Chamber events. Time-passed cards reduce future-visible totals naturally. No data reset, direct database write, broad CI, or workers restarted.

## All nine discovery categories revisited this pass

1. **Nightlife & Social:** existing Southern Barrel/Roasting Room and Greenhouse live, Sea Pines nightlife and Comedy Magic still held; first-party May River Theatre 2027 *The Producers* schedule newly identified, but dates/ticket records not yet distinct.
2. **Arts, Culture & Education:** **new May River Theatre** 2027 schedule and **new Michael Anthony's Cooking School** first-party adult classes, Arts Center, SOBA, Coastal Discovery remain held for exact parser/pins.
3. **Outdoor & Active:** existing Palmetto Bluff Conservancy 11 live; Sea Pines active excursions and Hunting Island field programs require individual meeting site coordinates; do not convert a resort geocache waypoint into an event pin.
4. **Food & Drink:** **new Michael Anthony's Cucina Italiana cooking school** official dated Squarespace pages; Dec 3/8/11/16/17/18/22/26/29/30 2026 + Jan 2 2027 originals, 11:30AM–2:30PM, 37 New Orleans Road Hilton Head. Venue street known, **robots access and independently verified event GPS not yet cleared**; no images imported. Existing food publishers still counted once.
5. **Family & Kids:** Sea Pines family holiday programs and SOBA kids courses held pending precise site/permission; no new independent qualified family source.
6. **Sports & Fitness:** Palmetto Running Company original collector already merged #367, but six canonical event URLs and start times collide with FindLocal; **hold source enrollment** until [app issue #1384](https://github.com/roomquestgame/RoomQuestGame/issues/1384) can correct incorrect FindLocal employer-office GEO and prevent duplicates. USCB public activity eligibility still unresolved.
7. **Markets, Makers & Shopping:** Bluffton Farm and Flea official 172 Bluffton Road November 22 and recurring market; require owner permissions/date-specific collector. SOBA holiday market; Sea Pines Sip & Shop. No double counts.
8. **Gaming & Hobbies:** Pink Palmetto Events Mahjong remains strongest distinct candidate with current official calendar + external ticketing. Event host venues differ (Tin & Tallow, Montage, Gifted, etc.), so no single-source centroid pin. Existing Beaufort library Mahjong is NOT a new publisher. Captain Jax merchandise without 2026 dated source remains exploratory.
9. **Civic, Volunteering & Community:** **Greater Bluffton Chamber now published** one original event; other syndicated ChamberMaster events prohibited. Town of Port Royal and Beaufort County bounded civic HTML still held for participant locations and tests. Beaufort Water Festival's official **Dec 5, 2026** public Holiday Boat Parade was found but is a standalone event page, not independently verified feed and is exploratory only.

## Two NEW candidate publisher rows (19 total holds, 0 release-ready)

- `michael_anthonys_cooking_school_hhi_sc`: [publisher's own calendar](https://www.michael-anthonys.com/cooking-school), [December 3 original](https://www.michael-anthonys.com/cooking-school/wicked-good-cooking-class-hilton-head-island-sc). Verified dates, times, original descriptions and numbered physical address. No already-published event at 37 New Orleans Road or same original URL found in read-only `external_events` venue overlap check. **Hold**: external robots.txt was not fetchable; no guess about permission, exact independent event-site lat/lon and tested parser with bounds/cancellation/dedupe still outstanding.
- `may_river_theatre_bluffton_sc`: [publisher original website](https://www.mayrivertheatre.com/) confirms *The Producers* **Feb 12–28, 2027**, Ulmer Auditorium, 20 Bridge Street, Bluffton. **Hold**: performance-level dates and event ticket URLs not yet verified; permitted-access/parser and building-event GPS pending. Read-only overlap returned FindLocal Town of Bluffton events at same street, so never use same-address alone to prove theatrical duplicates.

## Next release work

1. Pursue Michael Anthony's official site robots/terms, bounded Squarespace native ICS/page extraction and Census exact numbered restaurant/event site location; implement strict source canaries/tests only once all meet release gate.
2. Validate Pink Palmetto host-by-host numbered addresses/participation and event-specific ticket URLs; seek independent public gaming feed with validated GEO.
3. Advance Sea Pines, May River, Arts Center, SOBA, Farm & Flea and outdoor/civic candidates; pursue each of the nine categories, not only easy nightlife or museums.
4. Correct Chamber education category mismatch through #1392 without touching broad reclassification/overlays, and unblock Palmetto Running FindLocal duplicate wrong-GEO #1384 separately.
5. Recheck current live applied PG17 migration ledger and latest main before any new source enrollment; create **one consolidated, forward-only migration** for any ready feed batch, deploy exclusively protected `.github/workflows/db-deploy.yml`, check exact Vercel READY collector SHAs, then read back actual public cards. Publish 1–19 validated if below 20; **never pad the target**.

The St Helena library 1,451-VEVENT problem is already resolved by publisher-supported date bounding, now live; do not re-enroll it. St Gregory Parish Life Center stays staged until precise hall pin evidence.
