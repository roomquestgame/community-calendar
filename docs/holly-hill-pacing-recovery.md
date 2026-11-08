# Holly Hill collector pacing recovery

This batch addresses requests that the collector deferred itself before a
publisher received a calendar request. It builds on the durable publisher
wait receipts and successful iCal handoff in PR 99; those receipts are not
robots-policy storage.

## Admission and robots rules

`roomquest/preview_worker.py` caches a valid robots response for 300 elapsed
seconds after that response has been read and parsed. Cache hits do not extend
its lifetime. The cache holds at most 128 hosts, with the least recently used
host evicted first. Every requested path is evaluated against the cached
rules; the cache does not contain path-specific allow decisions. Only a valid
200 response or an explicit 404/410 absence is cached. Denials, temporary
errors and redirects outside the existing exact vendor exception remain
failures.

Robots admission now uses the enclosing source deadline. Its network timeout
is still at most five seconds, reduced when less time remains. The calendar
request's existing 18-second network budget starts after initial admission,
and is bounded by the same enclosing source deadline. Redirects share that
network budget. An expired deadline or a late wake-up prevents a new request.
No source, category or invocation deadline is extended.

Publisher waits remain host-specific. A local wait that does not fit the
remaining budget has a different code from an actual HTTP rejection:

| Outcome | Code | Collector classification |
| --- | --- | --- |
| Known local publisher wait will not fit | `publisher_pacing_deferred` | `source` / `pacing` |
| No request time remains | `source_fetch_deadline` | `source` / `transient` |
| Robots request receives HTTP 429 | `publisher_rate_limited` | `source` / `transient` |
| Calendar request receives HTTP 429 | `publisher_http_429` | `source` / `transient` |
| Robots rules deny the requested path | `robots_denied` | `source` / `access` |

A deferred attempt records no completed snapshot and stages no events. HTML,
exact iCal and the existing reviewed publisher-media routes retain their
v2/v3 pacing receipt fields. Legacy recorder routes retain their existing
payload. Bounded logs recognize the new code and do not invent an upstream
HTTP status for it. Optional ChamberMaster venue enrichment can retain its
existing unresolved-venue result when this local wait prevents the detail
request, just as it already does for other temporary transport failures.

## Backend deployment dependency

Deploy the batch's RoomQuest backend pacing classification and recorder
handling before the collector. The new `publisher_pacing_deferred` outcome
must take the early defer path in `rq_curator_gateway.record_preview`, before
publisher-failure accounting. That path uses the existing host `not_before`
and an appropriate scheduling floor, preserves publisher failure counts and
approval state, and only requeues work with active demand. It must not consume
the publisher failure retry budget or create a successful collection receipt.
All preview recorder versions converge on that function, including HTML,
iCal, WordPress and reviewed ChamberMaster sources.

This collector change adds no RPC or database schema. A legacy recorder call
does not supply new pacing fields; the backend must preserve its conservative
fallback in that case. Existing v2/v3 receipts must remain durable before a
ticket is released.

## Exact public display requests

Elloree's source adapter can collect its already reviewed advertised API
directly through `render_elloree_calendar()`. The source identity and event
attribution remain the public town calendar. The API request still checks
`connect.elloreesc.com` DNS, robots rules and pacing, uses the exact empty JSON
body, and cannot redirect. Requiring the town HTML page again before every
API collection would reintroduce the town host's 60-second crawl delay.

`render_old_santee_programs()` admits one anonymous RecDesk display request:

- URL: `https://oldsanteecanal.recdesk.com/Community/Program/FilterPrograms`
- Method: `POST`, accepting `text/html`
- Content type: `application/json; charset=utf-8`
- Referer: `https://oldsanteecanal.recdesk.com/Community/Program`
- Body: the public UI's fixed empty filters and first-page pagination below

```json
{
  "ProgramName": "",
  "Code": "",
  "ProgramNameXS": "",
  "DateRangeSelection": "",
  "DateRangeFrom": "",
  "DateRangeTo": "",
  "ProgramType": "0",
  "Age": "",
  "Facility": "0",
  "Days": "0",
  "Pagination": {"CurrentPageIndex": 1, "LoadMore": false}
}
```

The wrapper accepts only the enclosing deadline. Its second transport boundary
rejects changes to the URL, host list, filter body or method parameters before
network I/O. The existing public-DNS, robots, pacing, response-type, byte-size
and encoding checks apply. A POST redirect is never replayed. The adapter must
verify the displayed result count is complete within the observed default
25-item page before accepting a snapshot; transport success alone does not
establish completeness.

## Remaining boundary

The robots cache is process-local. A warm worker can defer a 60-second wait
and then resume with its still-valid cached policy. A newly started worker
has no such policy and must retrieve robots again, honoring the newly
observed delay before its calendar request. Repeated cold starts can therefore
still defer a host whose advertised delay exceeds the source budget. This
batch does not implement durable robots-policy storage or general resume
across worker restarts. The negative regression test keeps that limitation
explicit instead of bypassing the new request's wait.

## Verification

`tests/test_publisher_admission.py` checks elapsed TTL, cache aging, remaining
budgets, late wake-ups, the calendar network cap, warm deferred resume and the
cold-cache limitation. `tests/test_recdesk_transport.py` checks the exact
request and rejects changed actions, pagination, redirects, denied/private
destinations, oversized responses and invalid response types or encodings.
The transport-error and category-worker tests verify the new code survives
family normalization, reaches the appropriate recorder without staging or
completion, and remains distinct in safe diagnostics.

These are local fixture and mocked-transport checks. They do not establish a
deployment, live queue completion or published event count.
