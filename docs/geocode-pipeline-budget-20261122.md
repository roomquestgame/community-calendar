# Geocode pipeline optional-stage admission — November 22, 2026

## Problem and scope

`api/geocode.py` is the runtime caller of `venue_resolver.run_pipeline`. The
Vercel route has a 60-second function limit. The pipeline first gives the primary
geocoder its existing allowance of up to 45 seconds, then rotates an optional
address-evidence or photo stage. Previously those optional stages started fresh
15-second and 38-second budgets without accounting for elapsed geocoding time.

This is preventive scheduling and reliability hardening. The source establishes
the possibility of overlapping independent budgets; this review did not establish
a production timeout caused by it or measure savings from this change. Existing
transport timeouts, parsing and DNS resolution are cooperative rather than a
hard whole-request cancellation mechanism.

The address-evidence stage finds a publisher venue's actual address before
geocoding. It is separate from the retired venue-category typing queue. The photo
stage here is only a compatibility fallback: the existing `dedicated_ready`
capability continues to direct normal dedicated-media work away from this route.

## Admission rules

The pipeline uses one monotonic cutoff at 55 seconds from its existing start
point, planning five seconds of response headroom inside the route's 60-second
limit. It preserves the primary geocoder call and recomputes remaining time after
that call, including when the geocoder reports an exception.

| Stage | Existing work allowance | Reserved completion time | Admission |
| --- | --- | --- | --- |
| Primary geocoder | Up to 45 seconds | Existing worker logic | Runs first, unchanged. |
| Optional address evidence | 15 seconds | 11 seconds | Starts only when the full 26 seconds fit. |
| Media capability read | Existing 4-second RPC timeout | Response headroom | Skipped when less than 4 seconds remain before the cutoff. |
| Optional photo fallback | 38 seconds | 12 seconds | Rechecks after the capability read and starts only when the full 50 seconds fit. |

The address reserve covers one four-second completion RPC and the existing page
fetch's possible tail: its nominal eight-second allowance plus a final
five-second socket read can exceed the resolver's six-second admission guard by
seven seconds. The photo reserve covers up to three four-second completion RPCs
after the batch's parallel lookups. These are conservative admission allowances,
not enforced wall-clock bounds on every synchronous operation. A transport or
parse overrun remains possible; this change does not promise a 55-second finish.

If an optional stage does not fit, its result is `{"stop_reason":"deadline"}`.
The worker is not invoked, so no optional lease, attempt, provider request,
`needs_review` or `no_event_image` receipt is produced. Persistent work remains
available to a later eligible invocation. Short geocoder ticks can still admit
the compatibility photo stage; busy ticks defer it. An exact `dedicated_ready`
capability still returns `dedicated_worker` without invoking the fallback.

## Why an admitted photo batch keeps 38 seconds

The existing legacy media resolver returns `None` if too little time remains
after fetching/parsing HTML to probe the image. Its caller records that as
`no_event_image`. Reducing the work allowance could therefore change content
evidence, not merely postpone work.

An offline review using the actual resolver reproduced this: a four-second
claim, thirteen-second HTML fetch including the read tail, and one second of
parsing/dispatch caused a 26-second batch to write `no_event_image` without a
probe. The same inputs with the existing 38-second allowance successfully probed
and submitted the image. The pipeline therefore admits the full existing
allowance or skips before claiming. A future change that permits smaller budgets
would need an explicit deferred-result contract in the legacy worker/backend.

The same review exercised the actual address resolver with a first page taking
4.9 seconds, a second page taking 13 seconds, and four-second claim/completion
RPCs. It completed in 25.9 seconds, motivating the 26-second admission allowance.

## Preserved contracts and callers

The runtime delta is confined to `run_pipeline`. The primary geocoder's provider
routing, request limits, reservations, retry/receipt semantics, demand guards,
cached-result application and error isolation are unchanged. Standalone
`forward_geocoder.run_batch`, `venue_resolver.run_batch` and
`event_media.run_batch` signatures and defaults are unchanged. The repository has
no separate CLI caller of `run_pipeline`; ordinary direct Python calls retain
the same no-argument interface. API authentication and the cron configuration
are unchanged. The timezone worker and its empty-claim cached-result application
are outside this change.

## Focused local validation and handoff

Prepared against collector main `6a8bb06bbf3ac374423638e960f6970e085af7dc`, including
the concurrent Wildlife registration receipt change in #445. The baseline's
1,947 tracked file blobs were verified against that exact Git tree.

```sh
python -m pytest tests/test_geocode_pipeline.py tests/test_media_demand.py tests/test_venue_resolver.py tests/test_event_media.py tests/test_forward_geocoder.py tests/test_geoapify_geocoder.py -q
```

The focused checks cover primary geocoding first, stage-result preservation,
elapsed-time accounting after errors and capability reads, full-budget admission
and late skips, dedicated-media bypass, and optional failure isolation. Real
resolver/worker cases verify claim-to-submit behavior when admitted and absence
of claims or negative receipts when deferred. Existing geocoder, reservation,
media compatibility and venue evidence regressions remain in the command.
All database and publisher interactions are mocked; no live jobs are invoked.
Routine GitHub Actions remain disabled under the owner policy.

Local result: **166 tests and 267 subtests passed**, including 14 pipeline tests
with 19 subtests. Running the three real-worker regression tests against the
unchanged pinned baseline produced four expected failing subcases; the candidate
passes them. This establishes the changed admission behavior without production
load.

This document describes a local review candidate, not a production deployment.
After approval/integration, record the exact production revision separately and
observe normal `/api/geocode` traffic. A `deadline` optional-stage result means
deferred unclaimed work; it does not mean a database failure or a failed provider
request. Do not claim production cost savings without a comparable observation
window.
