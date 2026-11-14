# Atlantic City remaining calendars — November 14, 2026

This batch completes accessible calendars identified during the Atlantic City discovery pass. The first release already has 585 active public events across 11 collected sources, with exact staged/public description equality and complete New Jersey postal addresses. Those registrations and successful snapshots are not re-enrolled here. Visit Atlantic City remains paused after the production publisher returned HTTP 403; captured tourism rows are not represented as working coverage.

## Seven additional calendars

| Source | Publisher calendar | Captured eligible occurrences | Full description path |
| --- | --- | ---: | --- |
| Great Day Atlantic City | https://www.greatdayatlanticcity.com/events | 13 | Full Webflow detail body; bounded two-page manifest and durable complete-only checkpoints |
| Stockton Performing Arts Center | https://stockton.edu/pac/events-list.html | 16 | Complete public event cards plus the university's bounded native 25Live iCalendar narratives |
| Stockton Holocaust Resource Center | https://stockton.edu/holocaust-resource/events/index.html | 1 | Complete dated public lecture body, subtitle and actual room/address |
| Stockton Center on Successful Aging | https://www.stockton.edu/aging/events-workshops.html | 1 | Full public workshop card; duplicate PAC performances excluded |
| Absecon Lighthouse | https://abseconlighthouse.org/__static/jdj5jdewjglibdlvsvfqaurawvn6s3lr/2026-Calendar-of-Events.pdf | 1 | Entire remaining dated program paragraph extracted from the annual PDF |
| Oceanside I Family Success Center | https://oceanside1fsc.org/calendar%2Fevents | 6 | Current linked PDF, complete native descriptions and registration conditions |
| Oceanside II Family Success Center | https://oceanside2fsc.org/calendar | 5 | Current English PDF, complete native descriptions and registration conditions |

The captured replay contains **43 occurrences**, zero blank descriptions, zero over-limit descriptions and zero incomplete street/ZIP addresses. These were the pre-deployment expectations. Actual production collection now contains all 43 staged occurrences with matching full description hashes and postal streets. Forty additional events were public at the first completed readback; one Ducktown occurrence correctly matches the existing Noyes event, while two map destinations receive the reviewed points in the final correction batch. The machine-readable evidence records full-description MD5/SHA-256, dates, addresses and source identities for every expected occurrence.

## Description and schedule requirements

Every accepted row carries its entire normalized publisher narrative. The shared worker and database retain the existing 12,000-character capacity for these exact source profiles. Missing or oversized descriptions are held or fail explicitly; no summary, title, generated text or clipped excerpt is substituted. Worker tests exercise long descriptions through collection, checkpoint completion, staging and v2 preview recording.

Great Day only follows the upcoming collection and its real pagination. It completes the full manifest before staging, excludes three exact overlaps owned by the primary municipal/library feeds, and retains overlaps with Visit Atlantic City because Visit is not publishing. An untimed party, a parade without a resolved route-start street, and one Nov19 school event with a publisher name/street conflict remain held.

Stockton's public performance list supplies the schedule; its independently published 25Live export supplies additional complete narratives and room evidence. Native category copies must agree, and an export reaching its 200-row provider cap fails closed. Ticket links remain reader-facing identities; the collector never fetches the robots-disallowed ticket host. Sold-out registration is held. Explicit homeschool eligibility is preserved for the eligible student matinee. A conflicting native Nutcracker time does not overwrite the public performance schedule or manufacture an end time.

The Oceanside visual calendar grids require a reviewed date-to-cell mapping. Each mapping is bound to the SHA-256 of the exact current English PDF, and every collection re-downloads the publisher-linked document and extracts its complete native prose. **A changed monthly PDF requires review** and fails explicitly; this adapter does not project the November schedule into another month. Only the two reviewed 12.8/15.9 MB document objects receive a bounded 16 MB transport allowance. Other objects, redirects, hosts and content types retain the ordinary 3 MB limit, with unchanged robots, DNS, pacing and deadline checks.

The current Oceanside II PDF establishes the November 18 food distribution at noon–1 p.m. The apparent 1–2 p.m. conflict was stale indexed JFS content: its exact detail now returns 404, and a freshly retrieved November month page contains no such distribution. The current host calendar therefore supplies the accepted occurrence.

## Venue resolution

Every occurrence has a numbered street, city, New Jersey state and ZIP. Venue points are exact publisher associations, never regional coverage centers. Main/experimental PAC performances use the theatre building's published point, SCOSA uses the named Atlantic City campus map point, and the lighthouse and family centers use verified destination maps.

The Charlie Brown performance retains the verified Galloway campus street and a campus-level venue because its current room is not verified. HRC retains its actual L-112 Lecture Hall and the full Galloway street; no theatre point is substituted for that room.

Oceanside's November 19 Friendsgiving names Atlantic Cape Community College without a campus. Under Ben's explicit authorization for contextual street estimates, it uses **1535 Bacharach Boulevard, Atlantic City, NJ 08401-4485** with the visible venue qualifier **“Atlantic City campus (address estimated)”**. The college's prior Oceanside dinner at this campus and its current campus directory support that inference. The current publisher is not represented as confirming the 2026 campus, and no publisher GPS point is invented. Its full dinner narrative remains unchanged.

## Release and verification

Collector PR #211 deployed successfully before backend PR #912. Database run [43637780151](https://github.com/roomquestgame/RoomQuestGame/actions/runs/43637780151) applied the seven-source migration in one run and verified all 476 repository migration versions on production. Enrollment, coverage, demand and publication requests only target newly inserted IDs. Existing source keys/feed URLs are checked for collisions. The current helper, description constraint and completion trigger are narrowly patched with drift checks, preserving concurrent regional work.

Focused parser and real category-worker tests cover complete prose, source identity, schedules, deduplication, exact PDF editions, URL bounds, checkpoint durability and failure behavior. Captured source replay is not proof of production networking: this local environment's guarded publisher DNS check returns `dns_unavailable`. Final verification must read actual production source status, fresh staged snapshots and active public records, compare full description hashes, validate full postal addresses and list real unpublished rows rather than historical address-wait entries.

## Final preservation review

[The consolidated correction review](../../docs/evidence/atlantic-city-description-guard-review-20261114.md) records reproduced future-input cases, their source-scoped fixes, exact venue points and the distinction between retained narratives and rights-gated anonymous display. Current publisher narratives were unaffected; final rollout evidence is maintained with the application production audit.
