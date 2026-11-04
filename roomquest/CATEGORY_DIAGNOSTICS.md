# Category collector failure diagnostics — November 4, 2026

## Scope and compatibility

The category endpoint previously reduced every escaped `PreviewError` to HTTP
503 `collector_unavailable`, without retaining whether claim, collection,
staging, preview recording, publication or worker finish failed. An expected
source error successfully recorded in the database instead returns HTTP 200
with the existing failed counters. Those are different outcomes.

The approved follow-up adds bounded JSON messages to the existing application
logger `roomquest.category_worker`. It does not add a logging service, transport
request, dependency, retry, source demand or schedule. HTTP status/body contracts,
RPC arguments/timeouts, source-error dispositions and finish outcomes stay the
same. Release status and deployment evidence are tracked by the batch's app
repository handoff; this document does not establish a production rollout.

## Diagnostic fields

Each message has `event="collector_category_failure"` and only these fields:

| Field | Allowed evidence |
| --- | --- |
| `category` | Existing category vocabulary, or `unknown` |
| `phase` | `claim`, `fetch`, `stage`, `record`, `publish`, `finish`; `dispatch` is the HTTP-boundary fallback |
| `source_id` | Optional positive bigint returned by the database claim; absent for older responses or invalid/missing IDs |
| `rpc_operation` | Optional name from the six existing category/stage/preview RPC operations |
| `error_code` | Explicit fixed code vocabulary or bounded `publisher_http_100`–`publisher_http_599`; otherwise `unclassified_preview_error` or `unexpected_error` |
| `error_type`, `cause_type` | Fixed exception families; custom class names are never emitted |
| `upstream_http_status` | Optional integer 100–599 from an `HTTPError` or its explicit cause |
| `failure_scope`, `error_kind` | Existing source/worker diagnostic classification; these fields do not control retries |
| `elapsed_ms` | Monotonic elapsed time, bounded to 0–120000 |

No exception message, traceback, source key/URL, event content, token, ticket,
header, response body or user identifier is logged. Error codes use an explicit
vocabulary, so a secret that merely resembles a valid code is still excluded.
The transport is unchanged: SQLSTATE and database messages are not extracted
from HTTP response bodies.

For example, a preview-recorder HTTP 400 can now be distinguished from a claim
or publication failure by `phase="record"`,
`rpc_operation="community_collector_record_preview"`,
`error_code="database_unavailable"`, `error_type="PreviewError"`,
`cause_type="HTTPError"` and `upstream_http_status=400`. The client still receives
503 `collector_unavailable`; the diagnostic does not infer the database's exact
rejection reason from HTTP status alone.

## Primary failures and cleanup

The worker records a primary failure before entering its existing `finally`
finish call. A recorder or finish error therefore cannot erase evidence of an
earlier fetch/staging error. The worker emits at most three failure records
(source processing, recorder, finish) and suppresses repeated reporting of the
same exception. The category HTTP boundary supplies one bounded fallback only
when its exception lacks a worker report marker. Successful requests do not
emit failure records.

Finish keeps its original exception behavior: if cleanup itself fails, its
exception can still determine the HTTP response, while the earlier failure
remains visible in the logs. Diagnostics cannot prevent finish or replace a
source/worker result if the logging sink fails. This change does not retry a
failed operation.

The existing short HTML publisher handoff wait still runs before finish, with
its two-second cap and finish/response reserve unchanged. An interrupted local
handoff is reported as phase `finish` without an RPC operation; a failure of the
finish RPC includes that operation. The nested `finally` still calls finish
exactly once, including when both the local wait and the finish RPC fail.

The optional preview observer reports actual fetch, stage and record boundaries.
It coexists with the independent optional `publisher_handoff` argument; neither
observation nor handoff state enters RPC payloads or response results. Legacy
callers omit the observer and retain their exact result structure. Source errors
are still recorded before returning a failed result; only the existing HTML
`source_error` contract changes the lane outcome, with no change for WordPress
or other categories.

## Validation

Tests in the existing category-worker, central-entrypoint and transient-staging
files cover every RPC phase, the record-HTTP-400/503 path, escaped expected versus
unexpected exceptions, primary plus cleanup failure, unknown/custom error
redaction, old/malformed claim IDs, request isolation, nonfatal logging/observer
failure, unchanged HTTP bodies and unchanged RPC call ordering. They run in the
existing provider test workflow; no live collection is needed for these checks.
