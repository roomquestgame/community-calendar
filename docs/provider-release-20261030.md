## Provider collectors deployed and tested — October 30, 2026

Ben authorized this controlled three-source intake after migration-history repair, explicitly keeping the 15-minute Udell process off. Collector PRs [24](https://github.com/roomquestgame/community-calendar/pull/24), [25](https://github.com/roomquestgame/community-calendar/pull/25), and [26](https://github.com/roomquestgame/community-calendar/pull/26) merged. Production deployment `dpl_D864gMD44TTRqgzudFCrZ23ypfRZ` is READY at https://roomquest-community-collector.vercel.app from `0cfb45b8345a46248872659fe1e46fe1df0ffb40`. The geocoder module matches the previously deployed e6ef67b module byte-for-byte; the release preserves its live behavior rather than reverting to older main. No new collection Cron or SQL migration was added.

An empty POST protected by the existing operator secret invokes only a fixed three-source pilot (or its fixed Orangeburg-only retry). It accepts no URLs or source IDs, never calls the generic claim queue, geocoder or publisher, and writes through the existing token-checked staging RPCs. A privileged operator granted running leases to exactly source IDs 4827, 4888 and 4897; completed Squarespace sources were not re-fetched on Orangeburg retries. GET returned 404 and unauthenticated POST returned 401. Existing health endpoints responded successfully.

| Source | Privately staged | Source coordinates | Venue addresses | Result |
| --- | ---: | ---: | ---: | --- |
| Frazier History Museum | 10 | 10 | 10 | Complete |
| Mission Garden | 6 | 6 | 6 | Complete |
| Orangeburg County Chamber | 18 | 0 | 14 | Complete schedule; all 18 held for missing verified coordinates |

Orangeburg initially failed on optional detail transport. Safe PreviewError codes were masked by a broad ValueError handler; the follow-up preserves them. The collector now retains the complete validated XML schedule when optional ICS venue transport hits network/deadline/rate-budget errors, leaving unavailable venue evidence unresolved. The 20-detail limit, three concurrent requests, bounded deadline, robots policy and exact event-ID/start-time matching remain. Invalid XML, oversized schedules, robots denial or conflicting detail evidence still fail. Four Orangeburg records have no detail address; no chamber headquarters/default pin was substituted.

Final verification: all three preview statuses complete with no error, 34 staged rows total, zero public external_events for these sources, and none enrolled in community_factual_sources. Frazier and Mission remain approved; Orangeburg remains pending. ChamberMaster globally disabled, media worker disabled, daily geocoder cap 2300, and cron job 33 roomquest-udell-facts-refresh active=false. Existing minute geocoding is preserved. No automatic intake or public publication is activated by this release. These staged counts are not map visibility, native/device validation or app/Edge publication.

Validation: 117 targeted provider, preview, geocoder, venue, media and Mapsee tests plus 10 subtests; Python compilation, combined route dispatch and diff whitespace checks. The collector fork's CI remains manual-only; no required check was bypassed and no unrelated workflow was activated. Runtime error/fatal scan of final deployment over the latest five minutes returned no records. The protected end-to-end calls and independent database read-back establish actual intake, beyond READY metadata.

