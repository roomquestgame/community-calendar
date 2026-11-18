# EventQuest Batch 02 — ten external Localist feeds, live verification (2026-11-18)

**Scope:** The owner authorized small batches of 10 and requires checks for **complete publisher descriptions, real venue addresses and points, category/audience correctness, and legitimate event photo bytes and rights**. This audit verified exactly **10** previously proposed source hosts through public robots/API checks and a read-only production registry query. [Machine-readable evidence](public-localist-batch02-live-audit-20261118.json).

This is **source discovery/canary research, not ten activated sources**. No new Localist configuration, Supabase event, coverage registry, media record or mobile update was written.

## Current source check

| # | Official host | Live API | Publisher event count / window | Description over 2,000 | Event street / geo on sample | Disposition |
| --- | --- | --- | ---: | ---: | ---: | --- |
| 1 | [Hope College](https://calendar.hope.edu) | 200 | 212 / 30 days | 2 / first 100 | 92 / 92 of 100 | Hold: 61 descriptions blank |
| 2 | [Bryant](https://events.bryant.edu) | 200 | 67 / 30 days | 1 / 67 | 4 / 4 of 67 | Hold: event venues absent |
| 3 | [Louisville](https://localist.louisville.edu) | 200 | 211 / 30 days | 1 / first 100 | 76 / 76 of 100 | Hold: description and rights |
| 4 | [Yale](https://events.yale.edu) | **robots blocked** | — | — | — | No API request/bypass |
| 5 | [LMU](https://cal.lmu.edu) | 200 | 64 / 30 days | 1 / 64, max 4,400 | 48 / 48 of 64 | Hold: written reuse permission required |
| 6 | [UMSL](https://calendar.umsl.edu) | 200 | 83 / 30 days | 1 / 83 | 20 / 22 of 83 | Hold: venues and content/media permission |
| 7 | [Indiana University](https://events.iu.edu) | **API 404** | — | — | — | Not Localist; 19 existing LiveWhale/ICS source rows |
| 8 | [Lehigh](https://eventscalendar.lehigh.edu) | 200 | 72 / **7 days** | 8 / 72, max 2,290 | 33 / 35 of 72 | Hold: written reuse permission required |
| 9 | [Syracuse](https://events.syracuse.edu) | 200 | 812 / 30 days | 2 / first 100 | 62 / 77 of 100 | Hold: high volume and venue/rights checks |
| 10 | [Bentley](https://events.bentley.edu) | 200 | 50 / 30 days | 2 / 50, max 5,266 | 8 / 8 of 50 | Hold: very low location completeness |

Numbers separated by "/" in the **street / geo** column are two independent counts, not proportions. A two-number pair is relative to the last “of N” sample size. Source “total” is the publisher Localist API's `page.total_items`, not a count of validated EventQuest cards.

The dedicated `rq_curator_private.localist_sources` production registry has **85** entries and none of the 10 exact hosts. Separately, `public.municipal_event_sources` already has **19** Indiana University `events.iu.edu/live/ical/events/group_id/...` feeds; do not register a nonexistent IU Localist API or duplicate those ICS publishers.

### LMU content-quality evidence

A 30-day complete single Localist page contained **64** event records, of which **56** had descriptions, **48** had real numbered event streets and publisher GPS, **2** were virtual, and **8** event instances declared all-day. Three independently fetched original publisher pages contained the matching opening publisher narrative; this includes the long *Faculty Pub Night: Robert Welch* description of about **4,387 cleaned characters**. Factual details can be compared for correctness without assuming redistribution rights. Its Localist photo URL is a **candidate**, not an authorized event photo.

LMU [copyright policy](https://www.lmu.edu/copyright/) explicitly requires written permission to redistribute LMU text and images. Lehigh's [website copyright notice](https://www2.lehigh.edu/about/copyright) likewise requires express written permission for commercial redistribution. Localist's public [API documentation](https://developer.localist.com/doc/api) establishes technical access and widgets, not the university owner's transfer of copyright or photo rights. UMSL [calendar best practices](https://www.umsl.edu/marketing/web/calendar-bestpractices.html) require event photo uploaders to secure appropriate rights; that does not license EventQuest.

### Actual importer issue discovered and fixed safely in code

`RoomQuestGame/supabase/functions/discover-events/providers.ts` previously used `plainText(...,2000)` for all provider narratives. Every one of eight working Localist candidates has at least one longer description. Under the owner's rule, silently clipping these records is unacceptable.

Backend [PR #1226](https://github.com/roomquestgame/RoomQuestGame/pull/1226) adds **explicit source-config opt-in** `localist_full_descriptions: true` for **reviewed, approved dedicated Localist full feeds**. It preserves full sanitized descriptions up to **12,000** characters, rejects overlong records and leaves existing current source behavior unchanged. The exact source and five focused tests passed in an isolated Node runner, and the change was merged. This **does not** register or enable any university, change existing external-event rows, or authorize text/photo reuse.

Critical: the current database `public.external_events_description_check` still defaults to 2,000 characters. **Never turn on this opt-in** until a publisher-specific rights-cleared source has a safely deployed forward-only 12,000-character database CHECK exception, appropriate source-covering identity/refresh configuration, `allow_images:false` absent explicit image license, and verified import/preview/public-card receipts. This is intentionally separate from the active PostgreSQL 17 squash.

## Per-source admission checklist and no-change boundary

Each campus must pass the following before being included in EventQuest public events:
1. Actual robots and API permission, publisher-specific authorization for text reuse (not merely API reachability), credit and source URL.
2. A **full** bounded 30-day or reviewed rolling-source read with exact stable IDs and recurrence, cancellations, all-day semantics and original start/end/timezone, without gaps or fabricated start times.
3. Publisher-original narrative parity, actual event-specific venue street/coordinates (not campus or city center when venue unknown), category, holiday and audience overlays, separate source dedupe.
4. Per-event image rights, event image match and bytes/MIME reachability, **or ordinary fallback**. No automatic use of Localist image URLs.
5. Guarded source registration, source-scoped description-limit agreement between TS normalizer and DB constraint, normal demand/lease/refresh, and actual EventQuest Home/Events/Map live-card checks.

Every Batch 02 candidate is on hold, disqualified or requires rights review; **zero publisher events or photos have been published from this batch**. Don't create a second ruleset, rebuild/reset PG17, modify the existing unified classification/overlay workers, duplicate IU's ICS sources, or claim a GitHub merge is evidence of production admission.

## Follow-through and ownership

The most promising technical follow-ups are **Louisville and LMU** (substantial well-described events with many publisher coordinates), but LMU requires written permission before public republication; Lehigh also has an explicit copyright hold. **Bryant and Bentley should not be activated until the high rate of missing physical venue data is resolved.** High-volume Syracuse needs bounded full-feed/read performance verification. No guessed source, event venue or image and no changes to existing records are authorized by this research.

This PR contains no collector Python module changes and requires no Vercel production deployment. Its purpose is a durable actual ten-source disposition and explicit release contract. If a publisher grants reuse, the existing dedicated Localist worker is the right ingestion path—not a duplicate Python collector.
