# EventQuest Lowcountry ninth continuation — November 19, 2026

## Execution and release decision
New publishers deployed in this continuation: **0** (do not count prior 15); currently **15** approved Lowcountry sources. Read-only Supabase exact 15-ID audit: **326** staged records, **324** published scheduled source-associated cards, **309** future-visible cards. All preview complete, no new migration. Rolling target is 20 DISTINCT feeds but never force unvalidated or duplicate publishers.

## New functional collector (NOT safe to enroll yet)
- Palmetto Running Company `palmetto_running_company_sc`: merged collector [PR #367](https://github.com/roomquestgame/community-calendar/pull/367), SHA `f5b88faa4a2fcee1c9dd4972a3de6ab617a2deaf`.
- Robots * allows public HTML calendar and detail, disallows API/admin. Date-bounded 75 days/25 details; no automated disallowed API scraping.
- Live original Nov19 canary: **6** date-verified future original details with publisher full prose (270–1591 chars), direct event URLs, distinct occurrence IDs, mixed venues **94 Pope Ave Celebration Park, 30 New Mustang Dr Bluffton Middle School, 349 Hope Pond Way Unit 104 The Grind, 4211 N Okatie Hwy John Paul II School**. Actual per-event publisher GeoCoordinates used (not employer venue).
- Publisher JSON-LD appends misleading `Z` to local start times. Validated against visible `EST` and rendered calendar date, bound to America/New_York; unavailable end times remain NULL.
- Four focused unit tests and 16 earlier Lowcountry tests: **20 passed**, py_compile passed.
- **CRITICAL RELEASE BLOCK**: all six source original event links and start timestamps already exist as live `findlocal_public` cards! Existing FindLocal venues are all incorrectly assigned **30 Plantation Park Drive, Suite 202**, the *business's address*, even though the six events are at different actual streets. Deploying now could double-publish. Detailed audited exact links and correction safeguards in [app issue #1384](https://github.com/roomquestgame/RoomQuestGame/issues/1384). Do not ship source enrollment until canonical URL/start cross-provider dedup/preference is proven. No DB migration or production PRC source created.

## New geographic evidence (U.S. Census Public_AR_Current, independent)
Exact numbered-address matches: 97 Progressive St 32.272939834494,-80.915951812245; 185 Greenwood Dr 32.143341725004,-80.789236878718; 149 Lighthouse Rd 32.139612303419,-80.810175536415; 14 Shelter Cove Ln 32.179550569199,-80.727404581681; 172 Bluffton Rd 32.241498160977,-80.859289715187; 30 New Mustang Dr 32.25540699494,-80.87723364386. For multi-building Sea Pines resort the street point is not proof of exact check-in location; do not conflate source and event coordinates.

## All nine discovery lanes rechecked
1. Nightlife/Social: Sea Pines entertainment and Comedy Magic Cabaret already overlapping FindLocal, no deploy-ready new.
2. Arts/Culture/Education: Arts Center/Art League/SOBA/Coastal Discovery still need event-specific parser and GEO; new Pink Palmetto adult classes.
3. Outdoor/Active: Palmetto Bluff existing live; Sea Pines outing event pin pending.
4. Food/Drink: Existing Greenhouse, Roasting Room, Southern Barrel live; Pink Palmetto venue-based socials, not a separate feed.
5. Family/Kids: Sea Pines holiday family wagon, SOBA children; no verified new dedicated family feed.
6. Sports/Fitness: Palmetto Running original collector implemented but **all six are FindLocal exact duplicate URLs**, geo quality bug.
7. Markets/Makers: Bluffton Farm & Flea Nov22 at 172 Bluffton Road newly exact-Census-geocoded; publisher calendar/permission parser still missing; Sea Pines Sip & Shop.
8. Gaming/Hobbies: **NEW distinct first-party publisher Pink Palmetto Mahjong** https://www.pinkpalmettoevents.com/calendar with Nov20/21/25/28 and December/January dated classes at multiple venues; holder ticket detail/venue GPS + parser to do. Distinct from Beaufort County Library Mahjong publisher. Captain Jax no dated public first-party feed.
9. Civic/Community: Greater Bluffton Chamber original public dated entries via robots-permitted /events/catgid/6 and /events/details; 97 Progressive St exact Census match; remaining venues and bounded parser still pending. Port Royal and Beaufort County bounded municipal meetings require event room GPS.

**Queue**: 18 candidate publisher HOLD, 0 verified undeployed release-ready. St Gregory Parish Life Center remains staged only until exact hall GPS; St Helena oversized 1,451 VEVENT already date-bounded and live, do not re-enroll.

## Next execution
First fix FindLocal canonical collision and event-level physical GEO in app issue #1384, then consider PRC first-party enrollment only with zero duplicate public cards. Independently build bounded, event-detail validated Greater Bluffton Chamber and Pink Palmetto original Mahjong adapters. Shipping any first-party feed requires exact Vercel READY collector and **one forward-only PG17 migration after current applied live ledger**, pushed exclusively by protected db-deploy.yml on main. No broad routine CI, direct Supabase writes or squash/overlay disruptions.
