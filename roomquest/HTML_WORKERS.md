# HTML worker isolation and durable publisher pacing — November 4, 2026

## Problem and scope

One failing Virginia source previously delayed unrelated HTML publishers. The
collector recorded a truthful source error such as `event_schedule_missing`,
but returned only `complete`/`failed`/`staged` counters. `category_worker` therefore
finished every unsuccessful source with the same `failed` outcome used for a
database or worker failure. That applied a lane failure cooldown.

The companion backend change provides three bounded HTML worker slots with fair
publisher selection. Each slot can collect one independent publisher, allowing
up to three publishers at once while retaining one active fetch per canonical
publisher host. The shared publication cap remains two concurrent operations.
The existing deployment and demand callbacks serve all sources; this adds no
per-site deployment or cron. Collection remains on demand only and requires
approved sources and live, expiring demand.

This collector change distinguishes recorded source errors from worker failures
and persists publisher pacing evidence before releasing a slot. It adds no
route, scheduling service, timer, arbitrary URL input, or unbounded concurrency.

Bellevue Times remains strictly `first_page`: one registered calendar request,
at most 30 publisher cards, complete validation of that page, and its existing
source-specific absence-reconciliation protection. A malformed first page or
failed request never becomes healthy zero.

## Outcome contract

Failed processing results retain `complete=0`, `failed=1`, `staged=0`, with
sanitized `error_code`, `failure_scope` and `error_kind` metadata. Success counters
are unchanged. The original named `p_error` still records the source failure;
the new finish outcome is not a successful collection or permission to publish.

| Failure evidence | Scope / kind | HTML finish outcome |
| --- | --- | --- |
| Missing schedule, unverified listing structure, malformed event payload | `source` / `parse` | `source_error` |
| True robots denial, publisher HTTP 401/403, private DNS or unapproved redirect | `source` / `access` | `source_error` |
| DNS/network unavailability, unavailable robots, bounded collection/fetch deadline, publisher rate limit, HTTP 408/425/429/5xx | `source` / `transient` | `source_error` |
| Unregistered source/calendar, missing adapter or time-zone configuration | `source` / `configuration` | `source_error` |
| Database unavailable, staging deadline, collector configuration failure | `worker` / `infrastructure` | Existing `failed` |
| Unexpected local/staging exception or programming violation | `worker` / `unexpected` or `infrastructure` | Existing `failed` |

`source_error` is sent **only for HTML**, and only after recording the failed
preview succeeds. Other categories retain their existing `failed` scheduling
behavior. If staging, error recording, publication or finish itself fails, the
exception/legacy failed path remains available for bounded worker recovery.
An unexpected local exception is sanitized; publisher bodies and exception
details are not returned as diagnostic codes.

The backend accepts `source_error` only for the current, unexpired HTML ticket
with a new matching failed run. It releases the slot while preserving the
source's hold or `next_attempt_at`. Deterministic source/configuration/access
errors remain review or policy holds. Publisher transients get at most three
source retries at 1, 2 and 4 minutes, under active demand; the next failure goes
to review. Longer publisher waits always win. No retry occurs inside the parser.

The pre-existing worker retry branch remains limited to
`database_unavailable`, `staging_deadline`, and `collector_not_configured`.
Classifying a programming violation such as `unsupported_collector_rpc` as a
worker failure does not promise an automatic source retry. Normal code uses
only allowlisted RPC names. Existing finish recovery already uses `greatest`
to avoid shortening an established source backoff.

## Publisher waits survive a lost finish callback

Previously, `Retry-After` was discarded and crawl-delay lived only in process
memory. The HTML worker now calls the additive
`community_collector_record_preview_v2` RPC with the original six arguments
(including the collector token) and three explicit pacing arguments:

| Argument | Accepted value |
| --- | --- |
| `p_publisher_crawl_delay_seconds` | Integer 0–86400 |
| `p_publisher_retry_after_seconds` | Integer 0–86400 |
| `p_publisher_wait_unbounded` | Boolean |

All three are supplied on HTML success and failure. The RPC returns void, like
the original. It atomically records the preview and publisher wait before finish
releases the slot. Other source families continue using the original six-argument
RPC. Backend validation derives the canonical host from the registered source;
no raw header, hostname control string, publisher body, or error-string command
is passed to the database.

Per-collection `ContextVar` telemetry keeps concurrent and sequential previews
isolated. Cached robots rules copy their applicable delay into each collection.
Fractional numeric delays round upward; an independent pacing parser preserves
robots group selection while the original parser still decides path permissions.
Numeric and HTTP-date `Retry-After` values also round upward. The largest observed
wait is retained. Applying that wait from record time can conservatively wait
longer than necessary; it does not shorten the advertised interval.

Within the process, an existing Retry-After protects both calendar and robots
requests. A failed robots response is not cached, but an immediate second call
cannot issue another robots GET before the known host wait. Newly read crawl
rules also separate the robots response from the first calendar request. Every
wait remains within the existing request deadline; a wait that cannot fit ends
the collection with a named source error and its pacing metadata.

The shared transport continues to fail closed. Robots 401/403 or a disallowed
path remain `robots_denied`. Robots 429 becomes `publisher_rate_limited`; other
temporary robots HTTP failures become `robots_unavailable`, rather than falsely
claiming a policy denial. Private/non-public DNS remains `non_public_dns`, rather
than being accidentally wrapped as a transient `dns_unavailable` error. No user
agent substitution, challenge bypass or alternate transport is introduced.

### Oversized or unrepresentable waits require review

A valid advertised wait longer than 86400 seconds, or an unrepresentable
non-empty Retry-After/applicable crawl-delay value, is **not clamped** to a day.
The worker reports `publisher_wait_requires_review`, sets the unbounded flag,
and sends zero for both bounded numeric fields. It does this before staging a
successful preview.

The backend stores host pacing in `rq_curator_private.html_publisher_state`,
keyed by the lower-case host with leading `www.` removed. Its fields include
`last_dispatched_at`, `not_before`, `failure_count` and `last_error`. A bounded
wait extends `not_before`; it never shortens an existing deadline. An unbounded
wait sets `not_before='infinity'` and `last_error='publisher_wait_requires_review'`
and places the source in review. This host hold survives a lost finish callback,
lease recovery, demand expiration, successful records and ordinary source
approval.

Release requires a reviewed GitHub SQL migration that verifies the exact
host/source hold and the publisher's current policy evidence, then updates both
the host deadline and reviewed source state. This batch adds no automatic release
or new admin UI for that exceptional hold. No new timer or scheduling service is
needed; the existing demand queue enforces the persisted deadline.

## Narrow Virginia schedule correction

The official indexed page for [2026 Festival of Trees](https://www.dcr.virginia.gov/state-parks/event?id=2026-10-29-11-23-23-287887-qd6)
at Natural Bridge exposes a primary schedule starting November 13, 2026 at
10 AM and ending December 31, 2026 at 5 PM. The old clock–clock expression could
not match the intervening end date and reproduced `event_schedule_missing`.

The parser now reads the unique primary **When** value and accepts either the
existing same-day date/time range or an explicit start-date/time → end-date/time
range. It uses both provided dates with `America/New_York` DST validation. It
does not infer an overnight end, inherit missing meridiems, generate daily
sessions, or borrow dates/times from descriptions or “Additional dates.”
Missing, contradictory, malformed, ambiguous-DST and nonexistent-DST values
still fail the source without publishing a partial snapshot.

The indexed schedule was available during investigation; direct official page
and listing requests returned HTTP 403 and were not retried through another
transport. The fixture reproduces the published schedule text, not a newly
captured full publisher HTML page. The exact Smith Mountain Lake failing event
was not established, so this change does not claim to fix every such failure.
Virginia detail errors now log only the registered `source_key`, validated public
`event_id` and safe `error_code`, so a remaining failure can be traced precisely.

## Batch accounting and verification

Python already totals staging responses across batches: a 28-row collection
returns 28 for batches of 20 and 8. The observed run counter of 8 came from the
backend counter overwriting `stage_future_count` for named HTML sources after
each batch. The companion backend corrects that counter only; stage/upsert data
writes and publication counts are unchanged. Staged and publicly published
counts remain different measures.

Tests cover recorded parse/access/transient errors versus worker RPC failures,
HTML-only finish outcomes, atomic pacing payloads on success and failure, cached
rules, group selection, fractional waits, numeric/HTTP-date Retry-After, unbounded
review, no telemetry leakage, robots retry pacing, explicit Virginia ranges,
same-day/DST regressions and no staging after a bad later detail. They run in
existing test files already listed in provider CI; no workflow expansion or live
scraper audit is required.

Final local verification ran the exact pytest file list from
`.github/workflows/roomquest-provider-tests.yml`: **615 passed and 25 subtests
passed in 3.09 seconds** (3.53 seconds wall time). `git diff --check` also passed.
No live publisher fetch or scraper audit was run for this validation.

## Deployment compatibility

**Backend first, collector second.** Deploy the additive v2 RPC, validated
`source_error` outcome, publisher state/hold rules and fair bounded HTML slots
before this collector. The old six-argument RPC and legacy outcomes remain
supported, so the old collector is compatible with the new backend during the
transition. Deploying this collector first would cause the missing v2 RPC to
surface as `database_unavailable`; it must not fall back and silently discard
pacing evidence.

After the collector deployment is ready, use normal real-area demand to verify
source results, persisted host waits, cross-publisher progress and publication.
Rolling the collector back is compatible with the additive backend. Do not
remove the v2 backend contract while a collector still sends it.
