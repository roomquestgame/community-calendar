# Santa Cruz, California — next batch of 20 **verified new publisher feeds**

**Date of source checks:** November 18, 2026. This is a **new 20-source collector branch** and does not duplicate the preceding UCSC/Kuumbwa two-feed release or the six-source production batch (#266/#267). User instruction: pull **20 actual working feeds in each branch**, not twenty websites researched. This branch is **not merged or published**, and there is no new database migration.

## Verified live collector previews (9 / 20)

| # | New direct publisher and source key | Exact primary feed | Eligible future publisher events | Event location evidence | Full descriptions | Publisher photo candidates |
|---:|---|---|---:|---|---|---:|
| 1 | Abbott Square Market — `abbott_square_market_santa_cruz_ca` | `https://www.abbottsquaremarket.com/events?format=json` | **15** | Official event venue 725 Front Street, Santa Cruz CA; reject inherited Squarespace NYC default GPS | 15 | 15 |
| 2 | The Crepe Place — `the_crepe_place_santa_cruz_ca` | `https://www.thecrepeplace.com/shows-list?format=json` | **56** | Publisher's 1134 Soquel Avenue venue | 56 | 56 |
| 3 | First Friday Santa Cruz — `first_friday_santa_cruz_ca` | `https://firstfridaysantacruz.com/wp-json/tribe/events/v1/events` | **4** | Event-specific venue streets: Far West Fungi, Sterling Salon, County Government Center, Land Trust; one incomplete listing withheld | 4 | 3 |
| 4 | The 418 Project — `the_418_project_santa_cruz_ca` | `https://the418project.org/upcoming` | **14** | Official publisher venue 155 River St S, Santa Cruz CA, explicit next-event local clock; never invent future repeat schedules | 14 | 0 |
| 5 | The Catalyst — `catalyst_club_santa_cruz_ca` | `https://catalystclub.com/events/` plus bounded first-party show details | **15** | The Catalyst / Atrium, official 1011 Pacific Ave. Show time used, not doors time; all detail narratives first party | 15 | 0 |
| 6 | Santa Cruz Museum of Art & History — `santa_cruz_mah_calendar_ca` | `https://www.santacruzmah.org/events` plus matching original detail pages | **11** | Exact offsite event addresses retained: 705 Front St at museum, 261 Evergreen St at cemetery | 11 | 0 |
| 7 | Madson Wines — `madson_wines_santa_cruz_ca` | `https://www.madsonwines.com/events-2?format=json` | **12** | **Only** publisher-native `328 Ingalls Street, Suite G` occurrences; offsite arena, generic numbered street and closed notices excluded | 12 | 12 |
| 8 | Jack O'Neill Restaurant — `jack_oneill_live_music_santa_cruz_ca` | `https://www.jackoneillrestaurant.com/live-music/` plus own dated artist detail pages | **9** | Official 175 W Cliff Drive. Event card's date and show times cross-checked against publisher details; one empty artist description held | 9 | 9 |
| 9 | Stockwell Cellars — `stockwell_cellars_santa_cruz_ca` | `https://www.stockwellcellars.com/events?format=json` | **2** | Each Squarespace event independently confirms 1100 Fair Avenue, Santa Cruz; genuine publisher venue GPS accepted, fake NYC point rejected | 2 | 2 |
| | **Total publisher dry-run occurrences** | | **138** | All nine sources have complete native street evidence | **138** | **97** |

Source dry-run counts are **not** unique, deduped or public EventQuest cards. Images are **unlicensed candidates** until downstream rights and bytes check. The same event may appear in First Friday and another organizer. Source keys, original event URL hosts, complete descriptions and real wall-time occurrences are source-bound. No invented map pins, times, recurrence or generic Other categories.

## Verification and rollout safeguards

- Existing baseline targeted collector regression suite: **30 focused tests passed** in isolated Vercel sandbox, including new Madson/Jack/Stockwell fixtures; nine publisher modules exercised using the real guarded `preview_worker.preview_source` against primary sites (not test fixtures alone). All 138 accepted dry-run records have original full descriptions and event-specific streets.
- `roomquest/preview_worker.py` uses the original guarded fetch, robots+SSRF host allowlist and bounded deadlines. The Events Calendar sources, Squarespace sources, and HTML event-detail sources have separate reviewed identities.
- Current branch is **in development**. No PR merge, production Vercel deployment, source registration or fresh PG17 migration is claimed for these nine.
- When the 20 **independent working and new** publishers are verified, group the collector adapters in a small number of coherent PRs, merge/test, deploy the Vercel production collector, then use **only** GitHub's protected `db-deploy.yml` to run a minimal forward-only source-enrollment migration. Never touch the 2026-11-17 PostgreSQL 17 history-only baseline or existing production users/events.
- Live post-deployment checks must cover source uniqueness, complete preview receipts, downstream category evidence, street-level geocoding, rights/size image checks, duplicate suppression and public Home/Events/Map cards. Do not publish a source whose own feed is empty or blocked.

## Candidate sources still not credited toward the 20

The following require better native/structured feeds or reviews: City of Santa Cruz events directory (publisher event detail and individual explicit schedule, different civic/event venue addresses); Watsonville Public Library (programs include published first-party dates but calendar and recurrence contract needs validation); Roaring Camp Railroads (site HTML events with complex recurrence); Santa Cruz Beach Boardwalk and Civic Auditorium; Felton Music Hall (only two current shows with generic prose on Webflow calendar; need original performance details); Moe's Alley (10-second robots crawl delay, list cards have no full narrative); Bruno's Bar & Grill (large HTML page, check original dated cards); Hallcrest, Bargetto and Big Basin wineries (feeds not yet verified); Tannery Arts Center (Squarespace JSON returned zero individual events); Pajaro Valley Arts (tested TEC ICS returned **2023** archive only); museum/bookshop routes returning HTTP 403 (never bypass).

**Explicit false positive:** `santacruzbrews.com` is **Santa Cruz Brewing Co. in Santa Clarita, CA**, not the city or county of Santa Cruz. Do **not** import or count it.

After 20 verified source collectors have genuinely passed, move to the next 20-source branch and retain the same standards.
