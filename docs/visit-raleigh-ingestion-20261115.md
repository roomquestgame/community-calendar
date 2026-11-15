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

The complete 37-page native capture replay produced 3,506 unique normalized
`(id, starts_at)` records. It held 379 native rows with missing or ambiguous
times and one closed/cancelled occurrence. Multiple definite showtimes can
produce several normalized records from one native occurrence day.

The final canonical checkpoint is 614,143 bytes, below the unchanged 850,000-byte
adapter ceiling; its decoded payload is 4,478,303 bytes, below 24 MiB. Grouping
records by event ID keeps repeated full descriptions adjacent for compression.
Staging follows that immutable decoded order. The capture contains 3,488 records
with event coordinates and 18 with explicitly linked venue coordinates whose
listing identity and complete address match the event. No city-center coordinates
were introduced. Partial native addresses retain their actual publisher point.

Focused parser, worker, robots/checkpoint and neighboring source tests passed:
176 tests and 14 subtests. The worker checks cover complete capture before
staging, acknowledged progress, replay after a lost checkpoint, short-write
rejection, no publisher requests during staging, and no partial staging after
a publisher HTTP 403. Full descriptions and native image URLs were independently
compared with the complete source corpus. `git diff --check` passed.

## Release status

Implementation and focused verification are complete. Production collector
readiness, committed database deployment, complete staging and actual public rows
must be verified separately before reporting the source as live. Visit Atlantic
City's existing disabled source is outside this change.
