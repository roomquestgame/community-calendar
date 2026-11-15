# New York community and performance continuation — 2026-11-15

This batch adds four remaining calendars after the seven-source continuation in PR #230. It preserves the existing collectors and uses their ordinary guarded transport, full-description boundary, and complete-only durable checkpoints. The figures below are verified capture results; the companion backend production receipt records actual publication.

| Source | Official native feed | Verified upcoming occurrences |
| --- | --- | ---: |
| Prospect Park Alliance | https://www.prospectpark.org/events/ | 62 |
| Snug Harbor Cultural Center & Botanical Garden | https://snug-harbor.org/events-calendar/ | 89 |
| Jalopy Theatre | https://www.viewcy.com/api/o/jalopytheatre/courses | 37 |
| Brooklyn Art Haus | https://www.eventbrite.com/o/brooklyn-art-haus-65148790433 | 14 |
| **Total** | | **202** |

## Collector behavior

Prospect reuses the existing TEC parser and checks the complete native feed body against the event detail page. Snug uses the publisher's finite slots API for occurrence times and its entire event description block. Jalopy uses the publisher-linked Viewcy catalog and inert detail-page data; its native occurrence UUIDs identify each performance. Art Haus uses its exact native Eventbrite organizer, bounded pagination, full structured text modules, and verified single-event times.

All four profiles remain `html` / `html`, `America/New_York`. Each has a source-specific 200-item / 200-event checkpoint contract, a 900,000-byte cap, a four-hour checkpoint lifetime, and a 12,000-character full-body boundary. An oversized or missing body is held rather than shortened. Partial snapshots emit no stageable records. The complete manifest is revalidated before a finished collection can publish.

## Existing coverage and explicit holds

The two community calendars exclude 23 exact occurrences already published by working partner sources. Snug additionally recognizes the healthy Staten Island Children's Museum partner by its native label and official ticket hostname, preventing later mirrored dates from duplicating that source.

Ten virtual Snug slots, four slots combining distinct tour sessions, two multi-venue Holiday Hop entries, and two Prospect Fall Fix-Up dates with unresolved meeting details remain held. Art Haus retains 14 verified single events; its undated recurring parents, a different-venue Vinyl Night series, sold-out single events, and dates beyond the collection window are not converted into invented occurrences. Each decision is recorded in the capture receipts.

## Venue resolution

Locations use actual publisher-named venues, park features, entrances, and offsite destinations. Prospect's exact source-specific park/intersection exceptions preserve the event-linked point and complete street/postal reference. Snug's C/G/P building points are corroborated against official NYC evidence; six outdoor or campus features use visibly marked estimates from its current map. The conflicting historical `1000Y` PAD point was rejected. The native publisher's Snug ZIP remains intact with the differing PAD ZIP documented.

Jalopy's offsite anniversary remains at Gottscheer Hall in Ridgewood. Nine open-mic dates explicitly allow the adjacent tavern, and one event omits a structured venue while naming the theatre in its full body; these ten estimates are visibly labeled and bound to the reviewed native identities and wording. Art Haus singles retain the native 24 Marcy Avenue venue.

## Verification and rollout

The focused collector/worker suite passed 172 tests and 66 subtests on the final source files, including the narrow Snug alias correction and the current concurrent Boston dependencies. A final integrated readback also validated all 202 captured rows. Every accepted record has a complete description (230–4,100 characters), a reviewed street/postal reference, and a finite location. There are zero blank bodies, address gaps, missing coordinates, or duplicate native occurrences in the accepted capture.

Compact verification receipts are under `docs/evidence/new-york-community-performance-collector-verification-20261115.json`, `new-york-performance-capture-20261115.json`, and `new-york-community-expansion-{manifest,replay}-20261115.json`. Full normalized records and venue evidence belong to the companion `roomquestgame/RoomQuestGame` batch at `docs/evidence/new-york-community-performance-records-20261115.json`.

Deploy this collector commit before the companion four-source registration migration. Use one normal database deployment for the whole batch, then verify native-capture-to-stage and stage-to-public descriptions, addresses, points, approximate-location metadata, and existing-source preservation. No routine CI, transport bypass, TLS weakening, direct public-event writes, or separate per-source workflow runs are part of this batch.

Additional discovery dispositions for Gamestoria and Brooklyn Pop-Up are recorded in `docs/evidence/new-york-additional-triage-20261115.json`; no unverified source registration was added for either candidate.
