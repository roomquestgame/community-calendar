# Liberty public calendar — receipt 227

## Scope and evidence

Prepared against collector `9550503e797a3654ac66340f52f54035dde05392` for the
existing original receipt URL `https://events.liberty.edu/`, with source key
`municipal_50e2d01ac0c8331bc25fb21a`. No registration, recheck, source approval,
deployment, schedule, refresh cadence or production database change was made
by this adapter work. The 96-hour refresh and paused cron 44/59 are unchanged.

The ordinary public page is a Next application. Its current HTML references an
`AuthProvider` import with three same-origin hashed scripts. The shared helper
exposes named `getApiUrl` and `getApiToken` references and an anonymous calendar
fetcher. The read-only bootstrap uses the same fixed `[]` POSTs as that public
frontend. Both action IDs are discovered afresh from referenced scripts; no
build hash, action ID or returned token is configured or persisted.

On November 22, 2026, the public API origin returned by the getter was
`https://edn.liberty.edu`. An anonymous query using the page's own parameters
returned HTTP 200: page 1, 100 results per page, `datetimeStart asc`, November 22
00:00 through December 21 23:59:59, `published=1`, `groupOccurrences=false`.
It reported 82 results, one page, and a 341,154-byte JSON representation.
The reviewed robots requests for both hosts returned 404. Runtime robots
checks still run; a future denial is authoritative.

The final parser accepts **22 occurrences** from that response. It holds 59
with unknown, mixed, generic-campus, parking or placeholder locations (including
the Thanksgiving calendar marker). It separately holds event 17701: its
occurrence is 15:00–17:15 Eastern, while the public narrative says 5:45 PM.
The narrow contradiction check does not replace timestamps; clearly labeled
doors, arrival, registration and similar access instructions are exempt.

All retained dates are explicit occurrence dates, not generated recurrences.
The site's helper constructs a local JavaScript date from year/month/day/time;
the numeric `timezone:0` is not treated as a UTC assertion. The adapter resolves
these reviewed Lynchburg wall clocks to `America/New_York`, rejects DST gaps or
folds, and retains that timezone label. Identity uses `occurrenceId`, so separate
dates of one event retain separate IDs. Duplicate occurrence rows fail the
completeness check rather than concealing a missing row.

## Deliberately small venue map

Only the occurrence's own unambiguous building labels select an address. There
is no generic campus fallback and no inferred latitude or longitude. Ordinary
venue geocoding and review remain required, including for the two buildings
whose publisher uses the university street address.

| Publisher location family | Address | Primary evidence |
| --- | --- | --- |
| Montview Student Union rooms/tabling | 1410 Regents Pkwy, Lynchburg, VA 24515 | [Publisher floor plans](https://www.liberty.edu/business-relations/wp-content/uploads/sites/261/2025/04/Equiity-for-Africa-2021-Montview-Map.pdf), both sheets explicitly label the physical address of building 045. |
| LaHaye Ice Center rooms | 1971 University Blvd, Lynchburg, VA 24515 | [Ice Center contact and public events page](https://libertyclubsports.com/sports/2023/11/14/lahaye-ice-center). This does not cover the distinct LaHaye Event Space. |
| JF Library rooms | 1971 University Blvd, Lynchburg, VA 24515 | [Jerry Falwell Library location page](https://www.liberty.edu/library/about/location/), paired with the named library and its published address. The MSC postal box is omitted from the venue street address. |

Several rooms in one verified building can form one venue. Multiple buildings,
unknown buildings, parking lots and placeholders stay on hold. The exact event
link remains `https://events.liberty.edu/event/<publisher-slug>`.

## Transport and privacy boundaries

`read_liberty_public_action` allows only the two exact getter names extracted
from a same-origin hashed script. It supplies a fixed body, origin, content type
and Next action header. Callers cannot choose another action name, payload,
method or custom headers. `read_liberty_events` accepts only page 1, a fixed
30-day local date window and 100 results, with the published/ungrouped filters.
Only the fresh public getter supplies its transient bearer value.

Both specialized operations retain the shared DNS, public URL, robots, pacing,
Retry-After, request budget, deadline, status, content-type and body-size guards.
They never redirect, retry after a denial, use a fallback identity, or enter the
incremental snapshot cache. Getter responses have an additional 16 KiB bound.
The byte-counted Next result parser handles long string frames without logging
their contents. All errors are static diagnostic codes. The events token is
never an event field, URL, checkpoint, fixture or log message.

The entire calendar read is one complete page. More than 100 results, changed
page metadata, short pages, duplicate occurrences or a payload/schema change
fail closed. Empty eligible results remain a hold. There is no detail crawl,
guessed endpoint grid or private/admin operation. Runtime I/O is at most the
original HTML, three referenced scripts, two getters and one events page, with
ordinary robots admission within the caller's existing deadline.

The committed fixture contains seven selected visitor-facing events with only
event/occurrence identity, publication flags, title, slug, description, explicit
times and location labels. Creator/approver identities, administrative metadata
and actual bootstrap/token bodies were excluded. The contradictory hockey,
holiday and mixed-building examples are retained as hold tests.

## Integration owned by the recovery branch

This commit does not modify `registered_listings`, registration classification
or the reviewed-URL database allowlist. Integration must:

1. Add the **exact original URL** to the reviewed registered-HTML set and its
   database counterpart; keep the original receipt/source identity and use
   automatic detection. Do not ask the user to register the internal API.
2. Dispatch that exact URL/source key to
   `liberty_calendar.collect(source, fetch, deadline_at=deadline_at, listing=listing)`.
   Optional `fetch_action` and `fetch_events` arguments exist for fixtures;
   defaults use the guarded shared helpers above.
3. Bind ordinary Liberty GETs to `liberty_calendar.ALLOWED_HOSTS`, which is only
   `('events.liberty.edu',)`, and `follow_redirects=False`. Apply this to the
   **initial submitted-root fetch** in registration classification as well as
   subsequent HTML/script GETs and preview collection. The specialized API
   helper has its own separate `('edn.liberty.edu',)` scope.
4. Keep existing receipt eligibility, auth, cooldown, leases, audit and
   geocoding/publication gates. A code-ready reader is not a live recheck or
   proof of a published source.

## Validation

Final focused suite: **97 passed**, independently rerun by the US-adapter
reviewer. It covers current-bootstrap framing, rotated hashes/action IDs,
foreign/unreferenced scripts, one-page limits, incomplete/duplicate data,
publication filters, timezone consistency, occurrence identity, venue holds,
the narrative-time conflict and its doors/registration near-case, token/cache
privacy, exact operation scope, robots, denied HTTP responses, redirects, wrong
content types, body limits, request budgets and deadlines.

```sh
/workspace/scratch/10727a430742/ymca_unblock/venv/bin/python -m pytest -q --tb=short tests/test_liberty_calendar.py
```

Adjacent shared-transport and registered-listing regression checks:
**139 passed, two deselected**. The two existing
`test_worker_injects_recurrence_callback_only_for_brewing_and_saves_before_exposing_rows`
parameterizations fail `raleigh_direct_checkpoint_invalid` identically on
untouched base `9550503e797a3654ac66340f52f54035dde05392`; they were not changed.

```sh
/workspace/scratch/10727a430742/ymca_unblock/venv/bin/python -m pytest -q --tb=short tests/test_liberty_calendar.py tests/test_raleigh_next_social.py tests/test_registered_listings.py -k 'not worker_injects_recurrence_callback_only_for_brewing'
git diff --check
```

The independent review also passed the sanitized fixture through the real
shared normalizer: four retained fixture rows, all Eastern timezone and no
supplied coordinates. Cached live public evidence normalizes to the 22 rows
above. This is read-only extraction evidence, not deployed end-to-end acceptance.
