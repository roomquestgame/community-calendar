# Santa Cruz County — geographic × discovery-domain expansion checkpoint

**Readback:** November 19, 2026 (America/Los_Angeles). **Goal:** ongoing countywide direct-first publisher coverage, not a 20-source stop condition. Work in this branch only concerns a new, separately verified original publisher; other previously registered sources are not recounted.

## Production coverage benchmark (read-only)

49 approved regional publishers; 37 healthy completed previews, 34 with future public events. 461 future scheduled, non-hidden public event records with confirmed Santa Cruz County municipality venue addresses. Venue-city distribution: Santa Cruz 343; Felton 39 (37 from tourism/Ticketmaster); Watsonville 30; Soquel 26; Capitola 14; Aptos 5; Ben Lomond 2; Boulder Creek 1; Scotts Valley 1. No qualifying city-address public records for Bonny Doon, Davenport CA, Brookdale, Corralitos or La Selva Beach in this scoped query. These are counts of event rows, not independently deduped original events; source selection coverage coordinates are NOT venue coordinates. The clock/date-sensitive GOAT regression test is preexisting, not changed here.

## Nine source-discovery domains checked

| Original research domain, NOT EventQuest category | Verified work or held original-owner lead | Geographic emphasis |
|---|---|---|
| Nightlife & Social | **The Landing** performing arts center, first-party performing arts/comedy owner-calendar, two viable future detailed performances | Scotts Valley |
| Arts/Culture/Education | **The Landing** stage; another presentation of the same source, counted once only | Scotts Valley |
| Outdoor/Active | Santa Cruz Trail Stewardship original https://santacruztrails.org/events/ has timed future stewardship events; different trailheads/meeting points must be independently resolved; held | Santa Cruz mountains, Soquel forest |
| Food & Drink | Twin's Kitchen original https://www.twinskitchensantacruz.com/event-calendar lists some future market appearances but location-by-appearance and complete program narrative require review; not counted | county markets |
| Family/Kids | Boulder Creek Rec & Park District https://www.bcrpd.org/events lists Dec 5 Winter Festival and Dec 12 family show; dated flyers and event-specific street identity need confirmation; held | Boulder Creek |
| Sports/Fitness | Prior Santa Cruz Track Club/GOAT sources excluded from NEW count; seek specific organizer schedules with verified future dates | Watsonville, Scotts Valley, Aptos |
| Markets/Makers/Shopping | Downtown Santa Cruz Makers Market event at 1407 Pacific Ave is already covered by the Downtown Santa Cruz original publisher; do not duplicate. Separate organizer registration is not event feed | Santa Cruz, Boulder Creek |
| Gaming/Hobbies | The Game Night Collective is enrolled; Mythic Games/Game Santa Cruz still need live original tournament details and host permission, not aggregate reimports | Santa Cruz, Watsonville |
| Civic/Volunteering/Community | Volunteer Center https://scvolunteercenter.org/programs/adopt-a-family/warehouse-locations/ lists Dec 9–14 public gift-drop sessions but exact former Sears 41st Ave venue entrance/address must be verified before geocoding; held | Capitola |

## New original publisher: The Landing (Scotts Valley)

- Source key: `the_landing_scotts_valley_ca`; original owner URL `https://thelandingsv.org/`; exact first-party event pages in `https://thelandingsv.org/events/{slug}/` and official `251B Kings Village Rd, Scotts Valley, CA`.
- Host `robots.txt` returned HTTP 200 permitting this homepage with no crawl delay; strict HTTPS/event URL host and path identity, bounded homepage carousel of at most 24 cards, no pagination or inferred weekly repeats.
- Original structured JSON-LD supplies complete event narratives but **its timestamp hours conflict with visible venue schedules**. Collector explicitly takes the visible local Pacific start/end, checks same-day schema identity and date, rejects missing end clocks, private events, offsite changes, or missing original prose, and does not use mismatched metadata UTC hours.
- **Guarded live `preview_worker.preview_source`**: `p_error=None, p_future_count=2` (Stand up, Armando! Nov 19 8–10 p.m. PST; Fred Eaglesmith Nov 21 7–9 p.m. PST). Description lengths 260 and 2,285 chars. Both at the original publisher venue address, with no invented coordinates, no image rights asserted.
- **14 new tests passed.** Santa Cruz suite 234 passed, 1 older date-sensitive GOAT fitness test deselected (unchanged by this PR).
- These 2 are **development dry-run** occurrences, not registered, geocoded or publicly served before the protected source enrollment and post-release readbacks.

## Release safeguards

Existing owner authorization allows immediate small verified-source releases, even one feed. Collector PR and Vercel production READY must precede source enrollment. Use only protected GitHub RoomQuestGame `.github/workflows/db-deploy.yml` and forward-only migration; do not directly mutate production Supabase, alter PG17 squash, bypass robots, invent event street/coordinate/time, or assert publisher image license. Post-release verify source identity, complete production previews, Geocodio provider precision, dedup and public `external_events`. Continue research beyond this single source; no 20-feed stopping condition.


## 2026-11-19 evening — first countywide expansion worker: The Landing RELEASE RECEIPTS

- **Original source:** The Landing Performing Arts Center, Scotts Valley, canonical first-party `https://thelandingsv.org/`, `the_landing_scotts_valley_ca`. Official individual event pages in `/events/{slug}/`, original venue street **251B Kings Village Rd, Scotts Valley, CA**. No source-city or registration-office point substituted as a venue.
- **Collector deployed:** [PR #384](https://github.com/roomquestgame/community-calendar/pull/384) squash merge `535f54435bcca9b51b5b7d88ca0c218dd05f6db5`; [Vercel production deployment](https://vercel.com/room-quest-game/roomquest-community-collector/5fJhfnHbY8NbTfDwbKDKyYeeVwFk) `dpl_5fJhfnHbY8NbTfDwbKDKyYeeVwFk` **READY** at the exact collector SHA. Four source adapter/dispatch/evidence/test files and this county×domain audit. **14/14 new tests and 234/234 eligible Santa Cruz tests passed**, one preexisting date-sensitive GOAT fixture deselected.
- **Protected database source enrollment:** [RoomQuestGame PR #1405](https://github.com/roomquestgame/RoomQuestGame/pull/1405) merged `c6306808e30f8abf7740e1c43c8fdc35cb0346a1`; [protected db-deploy workflow #44652612135](https://github.com/roomquestgame/RoomQuestGame/actions/runs/44652612135) **completed success** and independently verified Supabase migration ledger `20261204150000` applied. This is a forward-only contract-guarded change, no direct Supabase write and no PG17 squash change.
- **Actual production readback:** **source ID 5913**, approved, `health=ok`, `preview_status=complete`, `preview_future_count=2`, `stage_future_count=2`, failure_count=0. Both event rows are staged `include`, with original titles, ends, full publisher narratives of 260 and 2,285 characters, exact venue street; at this checkpoint **0 new public external_events**, staged lat/lng NULL. Publication request priority 5 exists; no new Geocodio lookup outcome yet. These two are **not yet public cards**. Follow normal worker/geocoder queue; inspect and repair only through reviewed/protected forward-only migrations. Signed-in device view not independently verified.
- **Further original Boulder Creek lead (NOT yet verified/enrolled):** Boulder Creek Recreation & Park District `https://www.bcrpd.org/events` robots allowed, static publisher calendar advertises **Noon Year's Eve** Thursday December 31, 2026, **10:30am–12:30pm** at Boulder Creek Recreation Center. The district independently publishes the downtown facility at **13333 Middleton Avenue, Boulder Creek** via `https://www.bcrpd.org/rentals`. Verify the program's exact physical facility, owner-authored narrative, original occurrence identity, bounded native/Wix collection and safe image rights via the guarded collector before counting. The Dec 5 Winter Festival is a separate multi-site event with different locations and needs its own original meeting/check-in venue resolution.
- **Remaining priorities:** publish The Landing via true Geocodio/staging/categorization and verify public cards; fix Madson Wines source 5845 `database_unavailable`, Art League 5860, Dante 5878 and other worker contention under RoomQuestGame issue #1369. Continue nine-domain discovery with priority Watsonville, Scotts Valley, Aptos, San Lorenzo Valley and underserved rural coast. Never stop at 20/21 feeds; count each publisher once and count only actual future public events as delivery.
