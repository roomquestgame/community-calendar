# Dedicated image verification

`POST /api/media-demand` accepts exactly `{"ticket":"<database-issued UUID>"}`.
The endpoint accepts no source IDs, URLs, limits or credentials in its payload.
It consumes a one-use dispatch ticket through the existing scoped collector
credential. Nonproduction deployments do no work. The database enable switch,
singleton lease and current source/event evidence decide admission.

The Vercel function has a 60-second limit. Supported database runtime settings
are 20–40 seconds, with 40 seconds as the default. The drain uses at most 40 seconds from
entry, stops new claims early enough for a bounded probe and result submission,
and reserves additional finish/response time. Five executor threads are the
default; database configuration can select one through ten. Claims fill only
free execution slots. There is no fixed three-item run limit and no upfront
claim of a large queue whose leases could expire before execution.

One active drain lease makes the per-run request limit aggregate across
source-triggered, continuation and recovery invocations. Database claim logic
independently admits no more than three active candidate leases per host. A
shared in-process limiter applies the same host limit to each validated HTTP
destination, including redirects. Host keys are lowercase, omit a trailing dot
and remove a leading `www.`; request URLs and DNS checks retain the actual host.
Busy hosts are excluded from new claims, and a busy redirect defers its item
instead of waiting behind other leased jobs. Active publisher backoffs are
loaded at start and persisted on temporary HTTP failures.

## RPC contract

All calls use `community_collector_media_demand(p_token, p_action, p_payload)`.
The existing `supabase_rpc` helper supplies the private collector token; it never
appears in the HTTP dispatch payload, logs or public response.

| Action | Payload and response |
| --- | --- |
| `start` | `{ticket, worker_version: "media_demand_v1", candidate_only_version: "publisher_event_html_v2"}`. Rejection returns null/empty. Acceptance returns `{worker_lease_id, concurrency, per_host_concurrency, budget_seconds, host_backoffs: {hostname: retry_after_seconds}}`. |
| `claim` | `{ticket, worker_lease_id, limit, exclude_hosts}`. Returns existing media claim objects, including `media_key`, item `lease_id`, `candidate_only: true`, `candidate_url`, `event_url` and `title`. The backend enforces capacity and current eligibility independently. Exclusions are bounded to 128 hosts. |
| `submit` | Common worker identity plus `{media_key, lease_id, image_url, mime_type, evidence_url}`. The worker counts success only for `{recorded: true}`. |
| `fail` | Common worker/item identity plus `{reason: "no_event_image"}`. Used only for a completed negative validation, never for time or capacity exhaustion. |
| `defer` | Common worker/item identity plus `{reason, attempted, retry_after_seconds}` and optional `host`. Reasons are `deadline`, `host_busy`, `transient_http`, `network_error`. Delays are bounded to 1–3600 seconds. `attempted: false` releases an unstarted attempt. |
| `finish` | `{ticket, worker_lease_id, outcome}`; outcome is `complete`, `budget`, `failed` or `idle`. Always attempted after an admitted run; `{recorded: true}` acknowledges it. The backend releases any still-owned pending items and owns continuation/recovery. |

The backend fences every item operation with the active worker identity and
the item's lease. A lost submit acknowledgement must never be replaced with a
terminal no-image result; recovery resolves any still-owned pending claim.

## Image and source safeguards

The lane accepts only v2 candidates extracted from already collected publisher
event HTML. It cannot fetch a missing candidate's event page or substitute a
generic Open Graph image. URL checks, public DNS checks on each hop, manual
redirect validation, MIME/size/signature checks and a maximum three-request
redirect chain remain. Every request carries `Range: bytes=0-4095`; only one
4 KB prefix is read. The saved asset is a validated publisher URL, not an image
file copied into our storage.

HTTP 408, 425, 429 and 5xx responses are temporary. Numeric/date `Retry-After`
values are bounded and persisted without sleeping inside the worker. DNS and
network outages, exhausted run/probe time, and host saturation also defer work.
No image operation advances `snapshot_at`, `preview_checked_at`, or the existing
96-hour same-source freshness deadline. Publication continues to require exact,
current source/event/candidate evidence and a valid lease.

## Deployment and verification

Deploy the collector endpoint before enabling the database dispatcher. The
existing `community_collector_media` capability action returns
`{"dedicated_ready": true}` only after activation; unsupported actions on the
older backend keep the old photo path. Geocoding and venue cadence otherwise
remain unchanged. No image polling cron is added to Vercel.

The database dispatches after eligible source publication commits, continues
while genuinely due work remains and uses recovery for delayed or interrupted
runs. It must not loop on a mere count of pending rows: leased, stale, paused,
backoff-delayed and no-longer-demanded rows are not actionable.

Each completed admitted invocation emits a `collector_media_run` JSON record
with claimed, ready, unavailable, deferred, error/unrecorded counts, peak
inflight slots, stop reason, outcome and elapsed milliseconds. It includes no
ticket, lease, token, event text or publisher URL. Verify both queue age and
acknowledged completion throughput after enabling the backend.

Focused tests:

```sh
python -m pytest tests/test_event_media.py tests/test_media_demand.py tests/test_media_entrypoint.py tests/test_venue_resolver.py tests/test_roomquest_scoped_rpc.py tests/test_category_entrypoint.py -q
```
