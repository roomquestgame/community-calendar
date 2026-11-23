# Equal timed starts and ends remain start-only

## Problem and evidence

During the London and Cambridge expansion, native calendars supplied a valid
timed start but repeated that same instant in the optional finish field:

- Primrose Hill Community Library, <https://www.phcl.org/events.ics>:
  `8911@phcl.org`, `8912@phcl.org`, and `8913@phcl.org`, Saturday storytelling
  on 2026-11-28, 2026-12-05, and 2026-12-12 at 11:00 Europe/London. Staging IDs
  are 416610, 416626, and 416644.
- Rushden Historical Transport Society,
  <https://www.rhts.co.uk/wp-json/tribe/events/v1/events>: native ID 5668,
  <https://www.rhts.co.uk/event/brunch-with-santa/>, 2026-12-19 at 11:00
  Europe/London. Its official poster advertises a start only; staging ID 416587.

The native facts therefore establish starts, not advertised zero-duration
events. Their optional finishes should stay unknown. This does not resolve
independent venue, eligibility, audience, or source-approval decisions.

## Existing publication contract

A read-only inspection of the deployed functions on 2026-11-23 confirmed that
`rq_curator_private.publish_community_source_before_civic` already writes:

```sql
ends_at = case when r.ends_at > r.starts_at then r.ends_at end
end_time_verified = coalesce(r.ends_at > r.starts_at, false)
```

The shared `rq_curator_private.external_event_effective_end` uses three hours
after a timed start when the end is unverified. That is a visibility/expiry
window, not an advertised duration. The collector must not add three hours to
the event's public finish. The existing
[EVE-6 ingestion capability](https://linear.app/eventquest/issue/EVE-6/event-data-ingestion-pipeline-unified-architecture-current-state-and)
documents the same unknown-end behavior. No new backend timing rule is needed.

## Implementation

`roomquest/preview_worker.py::_preview` now changes an end to `None` only when
both values are aware datetimes and represent exactly the same UTC instant.
Normalization occurs before the existing retention check. Comparing UTC
instants preserves a real positive duration when a daylight-saving fold gives
the start and finish the same wall-clock label.

This shared builder is used by the actual registration and collection paths:

- ICS: `registration_formats.probe` / `preview_source` → `ics_adapter.parse`
  → `parse_ics_preview` → `_preview`.
- The Events Calendar: `registration_formats.probe` /
  `wordpress_adapter.collect` → `mapsee_adapter.parse_tribe` → `record`
  → `_preview`.

The change leaves missing ends, positive durations, before-start validation,
all-day handling, cancellation filtering, recurrence expansion and exceptions,
publisher timezone, URLs, and occurrence identities on their existing paths.
It does not broaden generic ongoing-event admission. Paths that already opt
into `retain_until_end` use their existing unknown-end fallback window.
Neither review decisions nor source approvals are written by this change.

The RHTS Santa Special native ID 5012 still spans December 5–6 in the publisher
response. Its separate session-versus-aggregate ambiguity remains a manual
Hold; this patch neither splits nor releases that event.

## Focused verification

The new `tests/test_zero_duration_end.py` has **23 passing tests** using
reduced native PHCL and RHTS fixtures plus explicit negative cases. Coverage
includes registration probes, real collection dispatch, mocked staging, all
three PHCL occurrences, all five RHTS entries, UTC-equivalent offsets, a
positive DST-fold interval, recurrence identity and EXDATE, cancellation,
date-only input, hidden TEC events, negative-end rejection, unknown-end expiry,
and unchanged generic ongoing admission. Live transport is prohibited in the
new tests.

The full focused command was:

```bash
python -m pytest -q tests/test_zero_duration_end.py tests/test_ics_family.py tests/test_ics_declared_timezone.py tests/test_ics_civic_dates.py tests/test_wordpress_adapter.py tests/test_tribe_zero_offset.py tests/test_registered_native_content.py tests/test_roomquest_preview.py
```

Result: **287 passed, 22 subtests passed, one existing assertion failed**.
`test_reviewed_zone_table_covers_only_audited_sources` expects seven entries,
while unchanged base commit `054e161` already contains eight, including the
reviewed Froglife Europe/London override. Both the table and its test are
unchanged by this work; the mismatch was confirmed directly from `git show
HEAD`. No timezone override was removed or relaxed to satisfy that assertion.
`git diff --check` passed.

Before PR creation, main advanced to `6af69d6` (PR #449, Forestry native venue
names and Wildlife explicit clock formats). The local branch was fast-forwarded
without conflict; none of the shared preview/ICS/TEC functions changed in that
base update. Repeating the command above with `tests/test_forestry_england.py`
and `tests/test_wildlife_publisher_clocks.py` added produced **401 passed,
22 subtests passed, and the same single pre-existing timezone-count assertion**.
Independent review also reran the new 23-test suite successfully. The paired
backend review separately tested refresh from an equal end to null with manual
Hold/Exclude decisions and notes preserved; that is not collector publication
authority.

Main advanced again to `6f1b4fc` while PR #451 was opened (PR #450, Wildlife
native dates with separate clocks). The patch rebased cleanly; shared
preview/ICS/TEC functions were again unchanged. The final rerun added
`tests/test_wildlife_native_date_clocks.py`: **437 passed, 22 subtests passed,
and the same single baseline timezone-count assertion**. No production code
or acceptance rule was changed to make that unrelated assertion pass.

This is local verification, not deployment or production acceptance. No
publisher refetch, source activation, geocoder request, or database write was
made to verify the change.

## Operational handoff

The patch is on `fix/uk-venue-auto-registration-20261123`, initially uncommitted
for independent review. See
[the registration handoff](../source-auto-registration-handoff-20261123.md).
A normal post-deployment collection should expose `ends_at = null` for the four
known start-only occurrences. Existing public publication already represents
such ends as unverified.

Staged venue-review identity includes the end field. A fresh normalized
snapshot may therefore invalidate a prior venue review for that occurrence.
Use the supported Admin review against the latest staged fact; never preserve
a stale identity or bypass a Hold to compensate. Verify the current manual
decisions and public end flags after the ordinary collection/publication flow.
