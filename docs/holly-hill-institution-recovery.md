# Public institution adapters for the combined recovery batch

`roomquest/holly_hill_institution_recovery.py` adds narrowly scoped collection for
Old Santee Canal Park and Orangeburg County YMCA. It uses shared event
normalization and injected guarded publisher transport; there is no network
client, browser automation, login or registration code in the adapter.

## Integration contract

| Source key | Registered identity | Internal evidence |
| --- | --- | --- |
| `old_santee_canal_park_sc` | `https://oldsanteecanal.recdesk.com/Community/Program` | Fixed public FilterPrograms POST plus canonical program details |
| `orangeburg_county_ymca_sc` | `https://columbiaymca.org/events/` | `https://columbiaymca.org/category/orangeburg-county-ymca/feed/` full-content RSS plus at most one detail page |

Both registered tuples use `kind=html`, `platform_adapter=html` and
`timezone=America/New_York`. Exact tuple validation runs before any callback.
Exports include `SOURCES`, `EVENT_URLS`, `PHOTO_URL`, `validate`, `event_url`,
`image_url`, and:

```python
collect(source, fetch, *, deadline_at=None, fetch_programs=None, diagnostics=None)
```

`fetch(url, accept)` is the worker's ordinary robots-aware, DNS-checked,
size-bounded publisher GET closure. `fetch_programs()` takes no arguments and
must be bound to `render_old_santee_programs(deadline_at=deadline)` in
`preview_worker.py`. The wrapper owns the fixed public URL, HTTP method, body,
Referer and Content-Type; redirects and caller-selected actions are prohibited.
No fallback calls the GET shell when this POST transport is unavailable.

The shared Holly Hill registry/dispatch and publisher evidence family routing
enroll these two sources. Backend URL/media validation must mirror the
exported patterns. RecDesk accepts only its exact canonical program detail path
with one positive `programId`. Its current pages have no event image allowance.
YMCA accepts dated canonical article URLs and raster images under its own
`/wp-content/uploads/sites/22/YYYY/MM/` directory, excluding logo, favicon,
avatar and pixel tokens. Query strings, fragments, credentials, explicit ports
and encoded/traversal paths are outside these patterns.

## Bounds and completeness

The adapter caps each document at 2 MB, the source at 30 seconds or the shorter
caller deadline, and output at 500 records. It checks deadlines before and after
requests; every required publisher failure propagates to the caller.

RecDesk requires one complete first display page, at most 25 advertised programs,
and every program's canonical detail page. The observed batch uses one POST and
five GETs: six required requests, plus the shared transport's cached robots
lookup as needed. It does not repeat the initial empty GET shell. A partial page,
changed result count, duplicate identity, unverified venue, failed detail or
schedule conflict cannot become a healthy partial source result. A genuinely
empty future display shape requires separate review rather than accepting the
initial page's placeholder as evidence.

YMCA requires one validated branch feed. It checks channel identity, article
identity, publication date versus dated URL, duplicate items and explicit
pagination links. At most one additional detail GET supplies missing event
artwork and verifies that current article facts agree with RSS. The captured
batch therefore needs two publisher GETs, compatible with the publisher's
ten-second crawl delay within the normal source budget. An event with its image
already present in full RSS content needs no detail request. Additional verified
RSS events remain eligible without additional artwork requests.

RSS describes the publisher's current branch feed, not every archived article
on the website. Unsupported article formats produce logged hold reasons, with
optional structured diagnostics for audit callers. If every potential occurrence
is held, collection fails explicitly instead of reporting a healthy empty
source. Columbia-wide venues and self-paced activities are explicitly excluded
from Orangeburg timed event output.

## Occurrence and venue rules

RecDesk uses only the Program Schedule table for occurrence dates and hours.
Enrollment dates, packet pickup and registration deadlines are preserved only
as explanatory facts. Listing dates and weekdays must agree with each schedule.
Explicit narrative time and fee labels must agree with their tables. Standard
registration fees are separated from optional add-on fees. Full programs retain
their public waitlist status; full is not treated as canceled. Registration age
limits and the narrative audience are preserved separately where they differ.

Exact reviewed room links and labels, together with the event's Interpretive
Center meeting statement, allow the public facility address at 900 Stony Landing
Road, Moncks Corner. The Tinsel Trot requires its own literal park address and
onsite race-day statement. The Camp Hall bird walk uses its explicit offsite
meeting address at 309 Avian Pavilion Ln, Ridgeville. Footer addresses never
repair an unresolved event location.

YMCA requires one literal WHERE/WHEN/TIME/COST block, a verified Orangeburg
branch address, member and non-member eligibility, explicit start/end clocks,
and a consistent weekday. If the occurrence omits its year, the dated publisher
article supplies that year; stale posts are never rolled into the current year.
Private and canceled notices are checked before description truncation.

Descriptions, categories, costs, audience, registration, availability and image
evidence remain attached to canonical event URLs. Shared normalization retains
an ongoing occurrence until its advertised end. No coordinates are invented.

## Verification

The fixture manifest records eleven public responses and the exact display POST
body. Representative replay of both original responses and reduced fixtures
returns five RecDesk programs and one current YMCA craft event. Regression tests
cover partial pages, shell placeholders, unsafe identities, deadline expiration,
required detail failures, offsite and room location boundaries, ambiguous or
conflicting schedules, fee and age preservation, full/waitlist status, private or
canceled notices, RSS identity, stale year handling, feed/detail disagreement,
XML entity rejection and the two-request YMCA budget.

Run:

```sh
python -m pytest -q tests/test_holly_hill_institution_recovery.py tests/test_holly_hill_recovery_pipeline.py
```

Publisher capture evidence and the expected six occurrence rows are documented
in `tests/fixtures/holly_hill_institution_recovery/README.md`.
