# Santa Cruz publisher completion handshake

Prepared November 22, 2026 against collector main
`4a3ac61bbb8e121ed27cca5c899efbb7057294b2`.

## Confirmed failure and narrow correction

Six enrolled HTML publishers successfully staged occurrences with
`image_extractor_version=publisher_event_candidates_v1`, but their dedicated
`preview_source` success responses omitted `p_parser_capability`. The worker
correctly routed them to `community_collector_record_preview_v3`. The deployed
gateway requires the matching capability as well as recent, complete staging
and matching per-row image observations. PostgreSQL rejected these completions
with SQLSTATE `22023`, `Incomplete Virginia photo extraction`; the collector's
generic database wrapper reported `database_unavailable`.

Add the existing `publisher_event_candidates_v1` capability to the five
dedicated successful return paths below. Each parser already attaches that
version to every accepted occurrence via `publisher_evidence.attach`, including
honest no-photo results. No parser, source identity, fetch bound, image selector,
rights decision, SQL validation, failure path or scheduler changes.

| Existing source ID | Source key | Dedicated parser |
| --- | --- | --- |
| 5859 | `the_fabrica_santa_cruz_ca` | `santa_cruz_fabrica` |
| 5861 | `chaminade_resort_holiday_santa_cruz_ca` | `santa_cruz_hotel_holidays` |
| 5862 | `dream_inn_holiday_santa_cruz_ca` | `santa_cruz_hotel_holidays` |
| 5863 | `downtown_santa_cruz_original_events_ca` | `santa_cruz_downtown` |
| 5874 | `goat_santa_cruz_hyrox_ca` | `santa_cruz_goat_fitness` |
| 5878 | `dante_santa_cruz_coffee_ca` | `santa_cruz_dante` |

The GOAT adapter's existing scope of up to six directly linked HYROX classes is
explicitly documented in
`docs/santa-cruz-ca-follow-on-20-source-discovery-20261119.md` (November 19,
12:04 UTC receipt). The capability certifies photo inspection for each collected
occurrence, as documented in `roomquest/PUBLISHER_EVIDENCE.md`; it does not expand
that collection scope. Fábrica can return its approved event photo candidate.
The other four parsers currently return no image candidate. No image is required
for event publication, and a capability does not grant permission to use images.

Source 5860, `santa_cruz_art_league_receptions_ca`, remains separate. Its observed
failure was the staging validator's incomplete narrative/street/event identity
check, before this completion handshake. This patch does not change that source.

## Offline regression evidence

`tests/test_santa_cruz_photo_completion.py` runs all five real parsers using their
existing captured-style HTML fixtures, followed by the normal worker staging and
completion calls. Its RPC double models the relevant deployed v3 metadata
checks; this is an offline contract test, not a live PostgreSQL execution.

The tests cover all six successful scopes, genuine empty results, candidate and
no-photo metadata, counts, server-owned observation timestamps, the historical
missing-marker rejection, failed/invalid parsing, staging failure, and stale or
incomplete staging that the capability must not override. Fetches and RPCs are
replaced with local fixtures; no publisher, queue or database is contacted.

```sh
python -m pytest -q --tb=short tests/test_santa_cruz_photo_completion.py
```

Before the production-source edit: **14 failed, 15 passed**, including all six
successful and all six empty completions rejected for the absent marker.
After the five return-path edits: **29 passed**.

Separately, the five original parser suites on unmodified main produced
**31 passed, 3 failed** on November 22. The three baseline failures use November
19/21 GOAT/Dante events with a real-time shared preview clock. New integration
tests freeze both relevant clock boundaries; the original tests and production
clocks are unchanged. No GitHub test workflow was dispatched, consistent with
the owner policy in `AGENTS.md`.

## Release and one-source acceptance

The backend already enforces this capability. Release through the normal
collector GitHub/Vercel path and verify the production deployment's exact commit
and READY status before a canary. Do not weaken the gateway or migrate source
records merely to accept the missing marker.

At the read-only 13:14:48 UTC check, all six sources were stale `running`, and
their demand expired at 02:45:24 UTC. Their normal worker eligibility was false.
Existing demand or an authorized existing-source preview request is necessary;
deployment alone does not restart them.

The agreed low-volume canary is existing **Dream Inn source 5862**. In Admin's
Advanced Data Tools, search Dream Inn, open Review, then use **Queue preview**.
This calls `community_source_request_preview(5862)`, which admits a stale running
source, queues that same source, adds 30 minutes of validation interest and
updates its existing publication request. It does not insert a new registration,
change rights or approval, or renew old event/image evidence timestamps.

The parser fetches one exact owner event page, plus normal robots evaluation:
`https://www.dreaminnsantacruz.com/activities/event-calendar/breakfast-with-santa-`.
Its existing expected event is **Dream Inn Presents Breakfast with Santa**,
December 12, 2026, 09:00–12:00 America/Los_Angeles, at
175 W Cliff Dr, Santa Cruz, CA 95060. Current fixtures have no photo candidate.
Live acceptance requires a new publisher read, current staged observations,
successful v3 completion with the candidate capability, and normal downstream
publication/hold readback. Old captured fixtures are never fresh evidence.

Only this existing-source canary is planned. The other five sources, source 6059,
new registrations and broader database queue repairs are outside this canary.
Code/test completion is not production or user-interface acceptance.
