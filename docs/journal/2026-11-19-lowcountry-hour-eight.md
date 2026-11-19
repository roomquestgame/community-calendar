# EventQuest Lowcountry: hour eight — 2026-11-19 15:41 EST

## Actions and live verification
Reviewed existing queue and seventh continuation; checked main branch and latest production Vercel READY deployment; re-read exact 15 production sources, published/staged rows, source approvals and preview states. No destructive or direct database writes.

- **New feeds deployed this run: 0 / 20.** No source satisfied all release criteria. **Ready queue: 0. Holds: 17.** The previous 15 enrolled feeds were not counted as new.
- **Read-only production:** 15 approved and preview-complete sources; staged total **326**, published scheduled public source-associated cards **324**, future-visible **313** (after time passed since prior 317); missing venue GEO **0**, missing numbered street **0** via POSIX digit pattern, category Other **0** from prior verification, 10 descriptions under 40 characters previously attributed to library branch feeds. Source keys/IDs in the permanent queue.
- **Latest collector production Vercel READY:** https://vercel.com/room-quest-game/roomquest-community-collector/5ahXukQP2vYnbDD4ZZkeDuGhbTyv SHA `c7c5c74f3f6863906ee5d7c34285201e6e4c12bf` (unrelated Gainesville changes; existing Palmetto source remains enrolled). No new collector PR or database migration required or attempted.
- **Current migration ledger** latest applied `20261201121500` (Gainesville Clermont). Any future Lowcountry migration must be a single consolidated forward-only PG17 version after this and any concurrent changes, protected db-deploy.yml only.
- **Collision spot check:** no scheduled matching Sea Pines sampled titles / 185 Greenwood text or sampled Chamber-owned titles in production query. This is NOT a guarantee of no duplicates. Art League workshops at 14 Shelter Cove in FindLocal are not Arts Center theatrical performances.

## All nine source categories rechecked
| Category | Real first-party findings and pending verification |
|---|---|
| 1 Nightlife / Social | New Sea Pines Nov24 full-moon wagon and entertainment date; Comedy Magic Cabaret conflicts with 29 future FindLocal cards and stays held; Chamber networking original events held. |
| 2 Arts / Education | Official Arts Center Cheyenne Jackson Dec15 two showtimes, Annie Dec2-Jan3 (do not synthesize individual shows), Coastal Discovery Botanica Nov24 and Dec17 curator's tour; no validated GEO/robust per-occurrence parser. |
| 3 Outdoor / Active | Sea Pines Nov24 outdoor ride, PRC Nov24 track and Nov28 run, state park varied meeting points; Palmetto Conservancy already live. |
| 4 Food / Drink | Southern Barrel, Greenhouse, Roasting Room already deployed; do not double-count syndicated Southern Barrel Tuesday Game Night in third-party Chamber listings. |
| 5 Family / Kids | Sea Pines Nov27 Caramel Apple Festival, Dec19 Polar Pines Express, Dec29 lights wagon, museum programs; Heritage Farm exact GPS pending. |
| 6 Sports / Fitness | PRC verified Nov24 5:30PM at 30 New Mustang Drive and Nov28 7AM at 349 Hope Pond Way Suite 104; Nov26 Turkey Trot and Dec13 Buffalo Run excluded until specific numbered meeting point. |
| 7 Markets / Makers | SOBA art school and Bluffton Farm & Flea remain held; existing Conservancy pop-up live. No unverified annual recurrence synthesis. |
| 8 Gaming / Hobbies | Captain Jax first-party https://captainjax.com/ confirms 24 Palmetto Bay Road Suite G but not a dated first-party games calendar, thus exploratory NOT eligible source; Library game events already covered, Sun City residency concerns persist. |
| 9 Civic / Community | Greater Bluffton Chamber first-party catgid/6 has exactly six future events Dec1/3/7/8/9/Jan12, details individually dated; exact per-venue geocode and robots pending. Bounded Beaufort county monthly HTML and Port Royal CivicEngage remain held. |

## New verified original event URLs
- Sea Pines Nov24 https://www.seapines.com/experiences/events/night-preserve-full-moon-wagon-ride-20 (17:15–18:15); Nov27 https://www.seapines.com/experiences/events/caramel-apple-festival (13:00–15:00); Dec19 https://www.seapines.com/experiences/events/polar-pines-express-holiday-wagon-ride (13:00, end unknown); Dec29 https://www.seapines.com/experiences/events/holiday-lights-wagon-ride (17:00–18:00). Each publisher page says Heritage Farm, 185 Greenwood Drive, but EXACT event meeting GEO independently unverified.
- PRC Nov24 https://shop.palmettorunningcompany.com/event/30642/TuesdayTrackNight (17:30, 30 New Mustang Drive); Nov28 https://shop.palmettorunningcompany.com/event/31337/BlufftonGroupRunWalk (07:00, 349 Hope Pond Way Unit 104).
- Chamber https://blufftonchamberofcommerce.org/events/catgid/6 six Chamber-owned dated events; do not count syndicated listings.
- Arts Center https://www.artshhi.com/performances (theater schedule); publisher venue 14 Shelter Cove Lane, but per-occurrence verification and collision audit pending.

## Deployment gate and continuation
1. Obtain independent exact numbered meeting-site GEO, starting with Heritage Farm at 185 Greenwood, Bluffton Chamber event-specific sites, PRC 30 New Mustang/349 Hope Pond. Neither the candidate centroid nor a neighboring building is eligible.
2. Check robots/terms via actual collector robots-aware fetch for first-party bounded pages, preserve full descriptions, restrict hosts and event identities.
3. Build and run fail-closed adapters/regressions on eligible candidates, verify net-new event identity against FindLocal and other existing providers.
4. Merge tested code, prove production Vercel READY at deployed SHA, and enroll batch through one newer protected PG17 migration; deploy any verified subset 1–19 if ready.
5. Reread this queue and journal next checkpoint; never re-enroll 15 active sources, do not touch St. Gregory unresolved hall GEO, existing squash/category/overlay workers.
