# Reviewed native zero-end fixtures

These are reduced snapshots of public publisher responses already obtained for
the London/Cambridge expansion. Tests do not refetch either site.

- `phcl-20261123.ics`: four selected VEVENTs and the original calendar
  header from <https://www.phcl.org/events.ics>, fetched 2026-11-23. UIDs
  `8911@phcl.org`, `8912@phcl.org`, and `8913@phcl.org` advertise Saturday
  storytelling on November 28, December 5, and December 12 at 11:00 with the
  same DTEND. UID `8625@phcl.org` is a real positive-duration control. Other
  VEVENTs were omitted and RFC continuation lines were unfolded for fixture
  formatting; dates, URLs, locations, descriptions, and timezones are unchanged.
- `rhts-20261122.json`: all five upcoming native events from
  <https://www.rhts.co.uk/wp-json/tribe/events/v1/events>, fetched 2026-11-22.
  ID `5668` repeats its December 19 11:00 start as the end; the official brunch
  poster advertises the start only. The other four events retain positive
  durations, including the separately held multi-day Santa aggregate `5012`.
  The fixture retains original identity, schedule, timezone, publication flags,
  category names, and venue address fields. Unrelated metadata, narrative,
  images, tags, and unused venue fields were omitted; pagination describes this
  five-record fixture. No time or location value was repaired in the fixture.

An equal timed end becomes unknown, not an invented three-hour advertised
duration. Category, venue, schedule aggregation, source approval, and manual
review decisions remain independent gates.
