# Visit Raleigh ingestion — November 15, 2026

## Scope and source evidence

Ben requested ingestion after review of the public calendar, RSS feed, robots rules,
and site terms. The source is `visit_raleigh_nc`, with publisher attribution
`Visit Raleigh`, calendar `https://www.visitraleigh.com/events/`, and timezone
`America/New_York`.

The calendar and `https://www.visitraleigh.com/robots.txt` returned HTTP 200 on
November 15. Robots allows the calendar and public data paths, disallows only
`/plugins/crm/count/`, and requests two seconds between requests. The public
`/event/rss/` export contains 30 excerpts, without authoritative occurrence times.
RSS `pubDate` must never become an event start time.

The public EventsApi configured by the calendar exposes the by-date collection at
`/includes/rest/plugins_events_events_by_date/find/`. The calendar supplies its
public frontend token and category scope. A bounded, slim query for November 15
through January 13 returned a total of 3,669 scheduled occurrence rows; the matching
unique-listing query returned 1,217. These are publisher counts before normalization,
time/venue validation, expiry and EventQuest deduplication.

## Data contract

- Use the exact 60 local calendar dates and the publisher's category scope.
- Read paginated occurrence rows through the existing guarded publisher transport.
- Interpret the API's end-of-day `date` sentinel as the local occurrence date,
  then combine it with the explicit weekday-specific `times` field.
- Preserve complete publisher prose, individual occurrence identity, public event
  permalink, event-specific venue/address, supplied coordinates and image provenance.
- Hold missing or ambiguous schedules and locations with counted reasons; do not
  substitute the publication timestamp, midnight, a city center or an organizer's
  headquarters for event facts.
- Keep the large snapshot in a bounded compressed private checkpoint, with strict
  expansion and record limits. Complete capture precedes staging. Persist staging
  acknowledgement progress and finish the source only after all accepted batches.
- Retain ordinary publisher pacing, source freshness, demand admission and existing
  publication/deduplication. Partial refreshes must preserve prior public events.

## Rights record

The official terms at `https://www.visitraleigh.com/legal/` restrict automated
extraction and commercial reuse. The source review records that observation and
Ben's subsequent instruction to ingest. Operational owner approval is not publisher
permission; keep `rights_status = 'unreviewed'` and do not assert a content license
or publisher consent.

## Focused verification

The complete 37-page native capture replay produced 3,502 unique normalized
`(id, starts_at)` records. It held 378 native rows with missing or ambiguous
times and one closed/cancelled occurrence. Multiple definite showtimes can
produce several normalized records from one native occurrence day.

The final canonical checkpoint is 614,367 bytes, below the unchanged 850,000-byte
adapter ceiling; its decoded payload is 4,471,545 bytes, below 24 MiB. Grouping
records by event ID keeps repeated full descriptions adjacent for compression.
Staging follows that immutable decoded order. The capture contains 3,484 records
with event coordinates and 18 with explicitly linked venue coordinates whose
listing identity and complete address match the event. No city-center coordinates
were introduced. Partial native addresses retain their actual publisher point.

Focused parser, worker, robots/checkpoint and neighboring source tests passed:
176 tests and 14 subtests. The worker checks cover complete capture before
staging, acknowledged progress, replay after a lost checkpoint, short-write
rejection, no publisher requests during staging, and no partial staging after
a publisher HTTP 403. Full descriptions and native image URLs were independently
compared with the complete source corpus. `git diff --check` passed.

A final independent schedule review found that bare unlabelled clock clauses
following weekday-labelled schedules could imply unsupported showtimes. Those
clauses are now withheld; explicit daily schedules and paired early/late shows
retain their stated scope. The correction passed 20 focused parser/worker tests
and nine subtests, plus another complete 37-page checkpoint replay. The totals
above reflect that correction. No Raleigh source was enrolled before this fix.

## Release status

The corrected collector was production READY and backend migration
`20261115112419` deployed successfully through Database deploy #322. The first
normal live collection of source 5666 at 11:38:25 UTC received
`publisher_http_403` during its initial calendar fetch. The source automatically
paused with zero staged/public rows and no checkpoint or completion receipt.
Research HTTP 200 access did not establish production access. The source remains
paused; no repeated publisher requests, alternate egress or identity changes
were used to work around the denial.

Read-only diagnosis also identified a separate request compatibility issue:
the documented API query is 3,418 characters, exceeding the generic 1,000-character
URL limit. The source-specific GET helper now validates the exact canonical
query under an 8,000-character bound, while retaining the actual full URL for
robots, DNS/pacing checks and HTTP transport. API redirects are rejected. Generic
URL limits, user agent, body limits and HTTP denial handling are unchanged.
This compatibility fix does not resolve the observed calendar 403.

The transport correction passed 196 focused/neighbor tests and nine subtests,
all offline or mocked. Root repeated the 52 Raleigh parser/worker/transport
tests and nine subtests successfully. Visit Atlantic City's existing disabled
source remains outside this change. Production ingestion requires resolution
of publisher access before the normal source can be resumed.
