# Santa Cruz — nine-domain hourly audit, 19 November 2026, 19:00 UTC

## Independent nine source-discovery domains (NOT EventQuest categories)

| Domain | Primary source discovery & evidence | Status |
|---|---|---|
| 1 Nightlife & Social | Moe's Alley original show calendar https://moesalley.com/tm-venue/moes-alley/ and genuine 1535 Commercial Way | Future original show end times not consistently verified; HOLD; Catalyst already enrolled |
| 2 Arts, Culture & Education | NEW Santa Cruz Mountains Art Center (SCMAC), https://www.mountainartcenter.org/call-for-artists-gift-of-art-2026/ | Owner's distinct Dec 4 First Friday Open House 5–7pm PST and Dec 19 Annual Holiday Sale 12–5pm PST, 9341 Mill Street, Ben Lomond CA 95005. Live guarded preview PASSED for two exact occurrences; proposed 18th new source |
| 3 Outdoor & Active | Santa Cruz Mountains Trail Stewardship https://santacruztrails.org/events/ and Coastal Watershed Council https://coastal-watershed.org/events/ | Event meeting locations vary or are released only after RSVP; do not substitute headquarters or city centroid; HOLD |
| 4 Food & Drink | Hallcrest Vineyards https://www.hallcrestvineyards.com/events and Cat & Cloud https://catandcloud.com/pages/locations | First-party future session date/end/detail/venue street not all verified; HOLD, no third-party syndication |
| 5 Family & Kids | Santa Cruz Museum of Natural History https://santacruzmuseum.org/ | Already registered as source 5799; do not recount. SPCA native calendar previously robots_denied |
| 6 Sports & Fitness | Tri Santa Cruz https://www.trisantacruz.com/ | Original 2027 race too far beyond 60-day horizon. Existing GOAT, Turkey Trot, Reindeer Run excluded |
| 7 Markets, Makers & Shopping | SCMAC Dec 19 owner holiday gallery sale | SAME publisher as arts; credit only once. SCM Makers Market https://scmmakersmarket.com/apply/ is a vendor application, NOT a dated feed; Tannery #16 previously deployed |
| 8 Gaming & Hobbies | Original Mythic https://gomythic.com/ and GAME Santa Cruz https://www.gamesantacruz.com/events | No independently verified owner-owned future full tournament record with start/end/description/street; existing Chess Club excluded |
| 9 Civic, Volunteering & Community | Santa Cruz volunteer center https://scvolunteercenter.org/ and city original https://www.santacruzca.gov/Events-directory | Meeting site-specific streets, end clocks or native robots permissions incomplete; City previously denied via guarded collector; HOLD |

## NEW SCMAC original publisher proof, not yet a public EventQuest card

- Publisher identity: santa_cruz_mountains_art_center_gift_art_2026_ca. Exact native tuple (html,html,https://www.mountainartcenter.org/call-for-artists-gift-of-art-2026/), America/Los_Angeles.
- No existing source identity or feed URL from read-only production Supabase duplicate check.
- Isolated Vercel sandbox santacruz-mountainart-20261119-hourly11, current GitHub branch tested. Publisher robots.txt returns HTTP 200 and asks for 10-second crawl delay; actual guarded first-party fetch using preview_worker.fetch_publisher(respect_robots=True, exact host allowlist) successfully returned 117454 bytes of owner HTML. This followed one transient source_network_error; no protections bypassed.
- Real preview_worker.preview_source executed on the new native adapter: p_error=None; p_future_count=2; p_venue_count=0. Full owner exhibit description, exact two future real event starts/ends and official source street 9341 Mill Street, Ben Lomond CA 95005. NO invented coordinates, images or synthetic recurrences. Pending normal Geocodio for event-specific street.
- New focused tests 11/11 passed, remainder Santa Cruz tests excluding unrelated stale original Nov 19 GOAT fixture 198/198 passed. Full suite has existing failing GOAT schedule assertion; do not claim clean full suite.
- At 2026-11-19 18:54 UTC existing collector production READY dpl_EBnfmsztrprPqFy8WJyDqxtd7gkL SHA 0cbd91bbdcc6888f3bea12e64d5669ce1a203ff4, preceding SCMAC release. NOT proof of SCMAC production deploy.
- Read-only production public EventQuest count in current follow-on = 28 future scheduled nonhidden rows: 23 Shakespeare + 3 Save Our Shores + 1 Agricultural History Project + 1 SCCMOD. Existing Madson Wines 5845 queued database_unavailable /22 failures, 0 staged or public; Art League 5860 same /11; Dante 5878 approved intake ready, two staged, running, 0 public. Fresh shared postgrest logs at 18:54 UTC show repeated SQLSTATE 57014 statement timeouts.
- Never directly mutate production Supabase or PG17 squash baseline. After merged collector and actual Vercel production READY, ONLY use unique forward-only RoomQuestGame migration through protected db-deploy.yml and independently verify ledger, approved source, staging, official-street Geocodio provider precision and public rows. Target 20 is not a release floor.
