# Santa Cruz follow-on: hourly original-source discovery and production truth

**Observed:** 2026-11-19 20:51–20:55 UTC. **Scope:** source-discovery audit and read-only production observations, not new collector enrollment. The nine lanes below are research domains, **not** canonical EventQuest event-category values. Each publisher is one distinct feed, even if relevant in several lanes.

## Production: source #19 already recovered downstream

Supabase read-only `public.municipal_event_sources` and `public.external_events` now show **19 separately enrolled follow-on publishers** and **31 future scheduled, nonhidden public server-side events from six of those**. This **supersedes** the earlier #19 robots/network-blocked and #18 not-yet-public receipts, without claiming device UI validation.

| Publisher/source | Current public future rows | Verified readback |
|---|---:|---|
| Santa Cruz Shakespeare / 5866 | 23 | Existing published rows |
| Save Our Shores / 5867 | 3 | Existing published rows |
| Agricultural History Project / 5885 | 1 | Existing published row |
| Santa Cruz Children's Museum of Discovery / 5891 | 1 | Existing published row |
| Santa Cruz Mountains Art Center / 5896 | **2 newly confirmed** | Approved, preview complete, 2 future stage rows linked to public IDs, official 9341 Mill Street Ben Lomond; published geographic point 37.088680,-122.088941, two non-Other arts_culture rows, complete narratives |
| City of Scotts Valley Recreation / 5899 | **1 newly confirmed** | Approved/health ok, preview complete, one future staged and published Crafts & Cocoa Dec 11 5–8pm PST, 360 Kings Village Road Scotts Valley; published geographic point 37.050515,-122.028097, category create, narrative present |

Exact source #19 readback: `preview_status=complete`, `preview_error=NULL`, `preview_future_count=1`, `stage_future_count=1`, `failure_count=0`, `preview_checked_at=2026-11-19 20:29:28 UTC`. This replaces the earlier transient `robots_unavailable` note. Neither new public result has an image URL; do not infer an image license. Production collector is **READY** on latest observed deployment `dpl_5ahXukQP2vYnbDD4ZZkeDuGhbTyv`, main commit `c7c5c74f3f6863906ee5d7c34285201e6e4c12bf` (a later Gainesville collector change; not a new Santa Cruz release). Protected historical source enrollment migrations remain applied.

The public venue geo coordinates above are real database readback; they were **not** invented in this audit. The stage rows themselves may have null native lat/lng; publication is using provider-resolved/cached venue location. No device UI card verification has been done.

## Still blocked separately

- **Madson Wines 5845**, an **older previously enrolled source**, remains `approved / preview_status=queued / preview_error=database_unavailable / failure_count=22 / stage_future_count=0`. Do not re-enroll or count as new.
- **Santa Cruz Art League 5860**, existing follow-on source, remains `approved / preview_status=queued / preview_error=database_unavailable / failure_count=11 / stage_future_count=0`. Do not invent publisher-side faults without evidence.
- **Dante Alighieri Society 5878** remains `approved / intake_state=ready / preview_status=running / preview_error=NULL`, two future included stage rows with external IDs but **zero public external_events rows** by exact source key. Stage linking alone does not prove live public publication.
- Supabase `postgres_logs` at **2026-11-19 20:54:12–20:54:35 UTC** continue to contain SQLSTATE `57014`, message `canceling statement due to statement timeout`. This is real ongoing platform load evidence, not proof of a specific Madson root cause. Diagnose queue/statement-cost and workers read-only before protected forward-only fixes; no direct database mutation.

## Nine original source-discovery domains — this run

| Discovery lane | Direct original leads, future-event evidence and hold |
|---|---|
| 1 Nightlife & Social | [Moe's Alley own schedule](https://moesalley.com/) displays original Nov 20 onward 2026 doors/show clocks; specific **end** clocks absent. Keep on hold, not event-ready. Previously counted Catalyst excluded. |
| 2 Arts, Culture & Education | **NEW lead: [Resource Center for Nonviolence (RCNV) event detail](https://rcnv.org/events/korea-is-not-a-war-base-dispatches-from-the-2026-jaju-solidarity-brigade/)**; publisher's own detail explicitly confirms **Nov 22, 2026 3–5pm PST**, extensive full narrative, at **612 Ocean Street, Santa Cruz, CA 95060**. Its homepage and own [contact/entrance page](https://rcnv.org/about/contact/) corroborate same physical event address and front entrance. Its individual event page offers an ICS download. RCNV is independent of prior publisher cohorts per read-only `municipal_event_sources` URL/name check, but **candidate only** until robots/host checks, native feed/ICS parsing, guarded live preview, recurrence/identity and rights gates pass. Earlier Santa Cruz Art League is already enrolled. |
| 3 Outdoor & Active | [Wilder Ranch guided coastal walk](https://www.santacruz.org/series/wilder-ranch-state-park-guided-coastal-nature-walk/) lists Nov/Dec timed sessions and **1842 Coast Road** on a tourism aggregator, **not original owner proof**; locate official state-parks organizer calendar/meeting point before credit. Santa Cruz Mountains Trail Stewardship original dig-day pages still need each event's correct trailhead rather than HQ. |
| 4 Food & Drink | [11th Hour Coffee own event page](https://www.11thhourcoffee.com/pages/events) still lacks sufficient complete dated 2026 future sessions. Previously enrolled Crepe Place, wine and Jack O'Neill sources excluded. |
| 5 Family & Kids | [Seymour Marine Discovery Center](https://seymourcenter.ucsc.edu/tour/) has owner-authored daily tours and Younger Lagoon select-day signup, official venue 100 McAllister Way, but **no exact future session booking schedule/recurrence verified**; do not turn opening hours into event occurrences. Also check overlap with UCSC existing source. |
| 6 Sports & Fitness | [Tri Santa Cruz organizer](https://www.trisantacruz.com/) has an August 2027 race, outside the 60-day collector future window; GOAT/Track Club already enrolled. Continue nearby original dated class/race searches. |
| 7 Markets, Makers & Shopping | [City original Antique Faire](https://www.santacruzca.gov/Government/City-Departments/Parks-Recreation/Santa-Cruz-Antique-Faire) advertises Dec 13, 2026 9am–5pm, named Lincoln Street/1100 Pacific Avenue; historical guarded City/faire fetch was robots restricted, **no bypass, no feed credit**. [SCM Makers owner application](https://scmmakersmarket.com/apply/) is an application, not an event feed. |
| 8 Gaming & Hobbies | [Mythic Games](https://gomythic.com/) and [GAME Santa Cruz](https://www.gamesantacruz.com/events) still lack publisher-native future event payloads with complete start/end/dates under a guarded fetch. Previously enrolled Chess Club/Game Night Collective excluded. |
| 9 Civic, Volunteering & Community | **RCNV** also qualifies as a civic *discovery* lead but must count only once total, not once in each domain; the original Nov 22 civic education event is physically held at the verified 612 Ocean Street venue. [Volunteer Center of Santa Cruz County](https://scvolunteercenter.org/) displays December donation center hours and virtual orientations, but event-specific physical venue/booking details are incomplete. No forced office geocodes. |

### Required next steps

1. Make an **independent guarded publisher fetch** for RCNV's exact event detail and original individual ICS link; check `robots.txt`, redirect/host/crawl policy, complete start/end and original full narrative. Test bounded import and stable event-specific IDs; preserve publisher metadata, timezone and description, avoid unlicensed images. A single original timed event is not automatically an ongoing calendar feed. Only then claim the **20th distinct verified source**.
2. If RCNV fails permissions, investigate other NEW original civic/arts/sports/makers/gaming publisher schedules, each as a separate candidate; 20 is the target, **not** a minimum release batch.
3. Diagnose Madson 5845, Art League 5860 and Dante 5878 queue/publication separately. Observe SQLSTATE timeouts and avoid blind retries/direct Supabase production mutations.
4. For any actual new source, merge only after tests + guarded preview, Vercel production READY, and source enrollment via a **forward-only versioned migration through protected `.github/workflows/db-deploy.yml`**. Verify source/preview/staging/Geocodio/public records; preserve PG17 squash baseline.
5. Keep the count precise: **19 registered**, **31 public future event rows**, **one new RCNV research candidate**, **zero new sources deployed by this documentation-only check**.

Reference production PRs: [collector #350](https://github.com/roomquestgame/community-calendar/pull/350), [protected SQL #1362](https://github.com/roomquestgame/RoomQuestGame/pull/1362), [earlier fetch hold audit #357](https://github.com/roomquestgame/community-calendar/pull/357). This file intentionally does **not** alter code, source enrollment, migrations, Geocodio mappings or image-rights flags.
