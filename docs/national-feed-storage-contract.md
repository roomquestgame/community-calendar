# Registered national feeds: private continuation contract

No sources are created by this capability. The existing signed-in Admin URL
registration remains the only enrollment route. Refresh remains demand-only,
with the existing 96-hour freshness policy.

## OpenActive

Use `kind=json`, `platform_adapter=jsonld`, the existing `jsonld` category, and
integer `registered_openactive_version=1`. Native content is independently
advertised with `registered_native_content_version=1`.

`community_collector_openactive_state` receives the ordinary injected `p_token`,
`p_category=jsonld`, private `p_ticket`, and `p_source_key` on every operation.
Validate the current lease, exact registered URL/hash identity and capability.
Only this private collector RPC may access the retained item table.

| `p_action` | Additional arguments | Response |
| --- | --- | --- |
| `read` | none | `{revision: int, checkpoint: object or null}` |
| `apply` | `p_expected_revision`, `p_checkpoint`, `p_items` (0–500), `p_reset` (default false) | `{revision: previous+1, checkpoint_saved: true}` |
| `items` | `p_after` (null or 64-char item key), `p_limit` (1–20) | `{items: [...], has_more: bool}` |
| `references` | `p_references` (0–20 native identity URLs) | `{items: [...]}` |

An updated item has `key` (SHA-256 of `feed_url + '\n' + kind + '\n' + RPDE id`),
`feed_url`, `kind`, `identity` (native `@id`/`id`, or null), `data` (object), and
`evidence_url` (the validated page that actually supplied the object). A deletion
has only `{key, deleted:true}`. `apply` performs deletes/upserts and checkpoint
CAS **in one transaction**. A stale lease or revision changes neither. `items`
returns ascending keys strictly after `p_after`; `references` returns matching
native identities in the same source's private table. No other source's item
may be returned. Limit an individual item to 60 KB and a write to 3 MB; read
responses are bounded at 1.5 MB. Retain full descriptions; overlarge items are
explicit errors, never truncated silently.

The stored `data` is the complete **projection input**, not an arbitrary copy of
unrelated booking-system metadata. Keep native identity/type/status, name,
description, image, explicit starts/ends, parent identity, venue name/address/
point and activity labels. Descriptive schedules retain their types/timezones;
actual scheduled children retain all projection fields. Better's observed
174 KB parent contained 168 KB of PartialSchedule entries. Their recurrence
rules must not generate sessions, so collapsing that non-projectable metadata
preserves all event facts and yields items below 2 KB on the captured
500-item page. A core projection above 60 KB still fails explicitly. A retained
page above 2.85 MB fails before any cursor advance, leaving room within the 3 MB
atomic RPC write limit for its checkpoint and ordinary metadata.

That actual Better series page is 3,758,455 bytes. The collector permits a bounded
8 MB GET only on that exact series endpoint/cursor path with robots enforced,
JSON Accept, and its single approved host. No guessed cursor, request timestamp
or authentication bypass is introduced.

The complete retained item set and final tail URLs survive successful refresh.
They are not transient staging and must not be erased by the existing fetch
checkpoint success-cleanup trigger. A reset clears this source's private items
and checkpoint only with the same lease/revision check. Reset is used for first
bootstrap, a changed stream set, or >=6 days since the last complete RPDE sync;
RPDE only guarantees tombstones for seven days. No guessed timestamp may skip
bootstrap. Public rows continue to use the existing complete-publication flow.

Checkpoint fields (only these keys):

```
version: 1
adapter: "openactive_rpde_v1"
source_key: exact registered hash
feed_url: original Admin URL
started_at: UTC ISO timestamp for this capture
last_complete_at: UTC ISO timestamp or null
phase: "fetch" | "stage" | "complete" | "ready"
streams: [{url, next, complete, pages, license, last_modified, last_id}]
stage_after: null | 64-char item key
record_count: nonnegative integer
venue_count: nonnegative integer
held_count: nonnegative integer
samples: array, <=8 rows and <=18 KB
```

`streams` is an exact ordered list from the reviewed profile below; `next` is
either that stream URL or its publisher-supplied cursor URL. Numeric `pages`
counts this capture only. `last_modified`/`last_id` hold the last observed item
position (integer or string/null). A completed stream requires an empty page
whose `next` is exactly the requested URL. No nonempty page, short page, HTTP
error or timeout proves completion. Only after all streams complete can `phase`
advance to `stage`. Every acknowledged staging batch is replay-safe; the
item-page cursor advances only after all rows from that page are acknowledged.
`phase=complete` means all retained items have been projected/staged; a successful
`community_collector_record_preview_v3` must atomically mark this private
checkpoint `ready` and set `last_complete_at` (retain all items/tails). If the
preview RPC fails, the next claim repeats the final preview, not a new capture.
The next claimed refresh turns `ready` into `fetch`, resetting stage counters
and using the saved tail URLs; it does not start at the beginning unless reset
is required. `fetch_pending` uses existing lease continuation, never a timer.

| Original Admin URL(s) | Streams (in order) | Public event host |
| --- | --- | --- |
| `https://better-admin.org.uk/api/openactive/better`, or its `/session-series` or `/scheduled-sessions` child | `https://better-admin.org.uk/api/openactive/better/session-series`, `https://better-admin.org.uk/api/openactive/better/scheduled-sessions` | `bookings.better.org.uk` |
| `https://bookwhen.com/api/openactive/sessionseries`, `https://bookwhen.com/api/openactive/scheduledsessions` | those two URLs, series first | `bookwhen.com` |
| `https://www.britishorienteering.org.uk/fullfixturesjson.php` | same URL | `www.britishorienteering.org.uk` |
| `https://api.letsride.co.uk/public/v1/rides` | same URL | `www.letsride.co.uk` |

Accept only HTTPS, the exact stream netloc/path, no fragment/userinfo/port and
cursor queries using `afterTimestamp`, `afterId`, `afterChangeNumber`, `limit`.
The collector always follows actual `next`, never constructs a guessed cursor.
Better and Bookwhen parent streams supply inherited facts; only their separate
ScheduledSession stream supplies occurrences. `PartialSchedule` is never
expanded. These profiles retain normal robots, DNS and pacing checks. Let's Ride remains
held wherever its robots endpoint returns 403.

Native proof uses the normal `registered_native_content_v1` envelope plus
`extraction=registered_openactive_rpde_v1` and `evidence_url` equal to the checked
RPDE page supplying the selected description/image. Event hosts are exactly
the table above. This proof describes extraction, not a licence or image-rights
exception. Publisher descriptions are kept complete, max 12,000 characters.

## Wildlife Trusts

**The national 500-item aggregate is discovery/routing only.** Admin registers
regional Trust URLs with their own accurate coverage. Do not create a national
Wildlife source for every local demand. Each regional source shares its own
96-hour result across searches in its area; its venue coordinates are retained
per event. Reuse existing BCN registration #336 for `/events` instead of adding a
second source for its equivalent RSS URL.

Use existing `html/html`, `fetch_checkpoint_version=1`, and a generic reviewed
`national_feed_v1` compressed checkpoint envelope bound to the registered URL.
The collector freezes the publisher RSS manifest, fetches every eligible detail
in bounded chunks, records explicit exclusions/holds, and stages only after the
manifest has been completely accounted for. Native HTML pagination is not
invented from the RSS feed. Feed contents and any explicitly advertised RSS next
links are consumed completely. `/events?` is robots-disallowed on the reviewed
Drupal publishers, so HTML query pagination is not an alternate path.

This module's exact envelope validator is the executable shape contract. It
uses the existing private checkpoint RPCs/CAS and <=850 KB compressed payload;
only a successful full preview clears that transient checkpoint.

The regional RSS manifest is limited to 2,000 entries across at most ten
publisher-advertised pages. A page at the observed upstream 500-item ceiling
without an explicit next link is held for completeness review. Each invocation
fetches at most eight detail pages; the retained prefix contains explicit
outcomes for cancellation, outside-window dates, missing event links, unreviewed
detail templates, ambiguous multiple-date schedules and publisher access denial.
Transient 503/network failures preserve the previous durable checkpoint and retry.

Native regional proof uses `extraction=wildlife_event_detail_v1`,
`description_field=wildlife_event_description`, and `evidence_url=event_url` on
that exact regional source host. Event descriptions are the full publisher
summary and about section. Images are candidates from the event's dedicated
photo field and continue through the existing rights/media workflow.

## Verification and rollout

The source fixtures are synthetic and model publisher markup captured on
22 November 2026. Tests cover complete-manifest and RPDE-tail certification,
transactional retries, late tombstones, parent joins, retained tails after a
96-hour refresh, reset after the tombstone retention safety window, native
content/media proof, scope rejection and full-description bounds. The capture
store RPC is exercised with an in-memory lease/revision harness, not production
database writes. The paired EventQuest backend migration supplies the actual private
store, completed-capture membership/point receipt and capability advertisement.

Local replay of already-captured publisher responses parses all first-page
items for Better (500 series and 500 sessions), Bookwhen (50 series and 50
sessions) and British Orienteering (500 legacy records). These are protocol
validation counts, not current event counts or completed bootstraps. The actual
BCN detail replay produced the publisher's 10:00–13:00 occurrence, Paxton Pits
address/point, and complete 1,345-character narrative.

Production readiness still requires paired collector/backend deployment,
Admin registration or recheck, and observing a complete leased capture and
ordinary publication. The collector makes no source rows and changes no
freshness schedule. British Cycling remains held when its robots endpoint is
403. Orienteering's legacy midnight/end-of-day placeholders are held without
fabricating clocks; rows need explicit usable session times. Bookwhen parent
metadata containing PartialSchedule is never used to invent dates. Its global
item cache must be projected/published through real geographic demand and venue
points, rather than assigning every item to the requesting location.

Primary protocol references:

- https://openactive.io/realtime-paged-data-exchange/1.0/
- https://developer.openactive.io/publishing-data/schedules
- https://developer.openactive.io/publishing-data/data-feeds/types-of-feed
- https://better-admin.org.uk/api/openactive/better
- https://data.bookwhen.com/
- https://www.wildlifebcn.org/events/rss.xml
