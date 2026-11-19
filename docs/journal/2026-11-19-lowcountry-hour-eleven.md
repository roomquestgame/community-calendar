# Lowcountry 11th execution checkpoint — 2026-11-19, ~18:34 EST

## Actual deployment and read-only checks

- **New publisher feeds deployed this check: 0 / 20 target.** No candidate passed all required robots, exact event GEO, tested parser and dedup checks. No code, migration, or production configuration changed.
- Protected PostgreSQL ledger read-only latest: `20261203150000`, newer than Chamber `20261203023000`. Do not choose an out-of-order migration number without rechecking at implementation time.
- Checked exact **16 existing approved source IDs:** 5803–5807, 5813–5817, 5873, 5879, 5886, 5889, 5894, 5907. All `health=ok`, `preview_status=complete`, and no preview errors.
- Staged-future source totals **327**; scheduled public source-associated cards **325** (not preview canaries); future public cards **309**. All 325 published cards have GEO, numbered street prefix, a non-Other category, and distinct (source_key, provider_event_id, starts_at). Ten library descriptions remain under 40 characters; no imported image URLs from these source feeds.
- Latest observed Vercel production READY SHA `577357fb556aac5ec9d572ad791df6bf3577608c` at [deployment](https://vercel.com/room-quest-game/roomquest-community-collector/DR4uzdHmPWU9L65Sqt7Vgab3dCUv). Commit ancestry verified GitHub ahead 2/behind 0 vs Chamber collector #372, ahead 6/behind 0 vs Palmetto Running collector #367. Palmetto Running remains **not enrolled** because all six exact canonical URLs/times already exist under FindLocal at mismapped headquarters; follow app #1384.
- Last five sources: Chamber #5907 1/1, Palmetto Bluff #5894 11/11, Roasting Room #5889 7/7, Southern Barrel #5886 8/8, Greenhouse #5879 1/1 (stage/public). Earlier Hilton Head and six Library sources are not NEW.

## Fresh independently owned calendar discoveries

1. **Gullah Kinfolk Traveling Theater** (NEW HOLD, `gullah_kinfolk_traveling_theater_beaufort_sc`): [official organizer](https://www.gullahkinfolktravelingtheater.org/), [Thu Dec 3 7–9 PM original ticket detail](https://www.gullahkinfolktravelingtheater.org/events/2026-christmas-wish-freedom-thursday-uscb) and [Fri Dec 4 7–9 PM original ticket detail](https://www.gullahkinfolktravelingtheater.org/events/2026-christmas-wish-freedom-friday-uscb), same publisher event `Christmas Wish...Freedom`, **USCB Center for the Performing Arts, 805 Carteret Street, Beaufort SC 29902**. Genuine new first-party dated original event pages, public adult/youth tickets, substantive publisher narrative; no directly matching source-address/title external public rows in sampled audit. HOLD robots, verified check-in GPS, safe Wix listing parser + tests and comprehensive collision check. Do not count the two performances as two feeds.
2. **Farmers Market of Bluffton** (NEW HOLD, `farmers_market_bluffton_sc`): [official organizer schedule](https://www.farmersmarketbluffton.org/), normally **Thursday 12–4 PM** at **68 Boundary Street, Martin Family Park, Bluffton SC 29910**, but officially **open Wednesday Nov 25, closed Thanksgiving Thursday Nov 26**. Third-party event directories conflict by listing Thursday Nov 26/12–5; original publisher takes precedence. HOLD no date-specific event-detail URLs, publisher robots, verified park pin, recurrence cancellation and duplicate tests; static organizer schedule alone does not satisfy full new-feed release requirements.

## Other priority canaries

- **Michael Anthony's Cooking School** [full first-party index](https://www.michael-anthonys.com/cooking-school) currently visibly publishes dated individual original class pages/ICS (Nov 20/24/25/27, Dec 3/8/11/16/17/18/22/26/29/30 and Jan 2); example [Dec 8](https://www.michael-anthonys.com/cooking-school/dinner-with-friends-cooking-class-hilton-head-island-sc). Class venue is **37 New Orleans Rd, Hilton Head Island**, generally **11:30 AM–2:30 PM**; publisher supplies full menus and event narrative. Robots file and Squarespace `?format=json` could not be independently fetched in this evidence channel. Do not infer permission or fake independent GEO. This is existing HOLD, **not new discovery**.
- **Pink Palmetto Mahjong:** source search index was current (Nov 20–Jan classes), while a separate HTML cache view exposed older Oct/Nov entries. Treat as possible source snapshot/crawl inconsistency; require live authoritative calendar/detail canary and each host's exact address; do not promote.
- **St Helena Library:** its 1,451-VEVENT source is already date-bounded and enrolled; preserve it, no duplicate enrollment.

## Nine discovery lanes — explicit findings and holes

| Lane | This checkpoint's result |
|---|---|
| 1 Nightlife/social | Sea Pines entertainment still held, Gullah theatrical performances new; Comedy Magic overlaps 29 future FindLocal |
| 2 Arts/culture/education | **NEW** Gullah theater two original dated pages; Arts Center, SOBA and Art League remain holds |
| 3 Outdoor/active | Existing Palmetto Bluff live; Sea Pines Fishing/Wagon and Hunting Island differing meeting points remain held |
| 4 Food/drink | Michael Anthony 15 dated cooking classes revalidated, original Greenhouse/Southern Barrel/Roasting Room active; **NEW** Farmers Market food vendors organizer |
| 5 Family/kids | Gullah youth-ticket tier, Sea Pines family programs and SOBA workshops; both new publisher and prior holds need exact GEO |
| 6 Sports/fitness | Palmetto Running code exists but all six exact FindLocal overlaps block enrollment, USCB fitness public eligibility unverified |
| 7 Markets/makers/shopping | **NEW** Bluffton Farmers Market schedule with special Thanksgiving exception; existing Farm & Flea, SOBA and Town holiday market holds |
| 8 Gaming/hobbies | Pink Palmetto Mahjong current index vs stale HTML mismatch requires live authoritative source and multi-venue detail/GEO |
| 9 Civic/volunteering/community | Existing Greater Bluffton Chamber now live, bounded county monthly and Port Royal calendars held; market community schedule new |

## Release queue, gates, and next actions

- **21 independent publisher holds** (19 carried + 2 new). **0 verified and undeployed**. Nothing ready for safe DB enrollment.
- Gullah: robots and Wix first-party list access; coordinate at exact USCB event entrance; bounded extraction and category/dedup tests; if all pass, independent small release using a single post-ledger forward-only PG17 migration via protected `.github/workflows/db-deploy.yml`, Vercel READY commit ancestry first.
- Michael Anthony: publisher access/robots; registered Squarespace class calendar JSON/HTML parser; independent exact 37 New Orleans Rd GPS and original event-level canonical narrative; compare against all providers before publishing.
- Pink Palmetto: solve live index mismatch and per-host address problem; reject private entries or same-owner duplicate host listing.
- Never change completed squash baseline, St Gregory staging, unlicensed images or unrelated workers. Maintain no-default-Other and exact event GPS gates.
