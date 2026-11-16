# Missing time zones: coordinate fallback (EVE-65)

`/api/timezones` is an independent authenticated five-minute background job using
`timezonefinder==9.2.0` and `timezonefinder-data==4.2026.6` offline. Geocodio,
venue geocoding, source schedules, native UI and public page loading are unchanged.

The backend migration adds a private exact-coordinate cache, leased batches of
50 unique points, and a bounded 100-event backfill per invocation. Positive and
unresolved results persist; concurrent/replayed/expired lease submissions cannot
overwrite completed results. Only pending expired leases are retried. Cache
version upgrades require a deliberate review, not a recheck on page view.

A write trigger reuses cached zones for new imports. Existing source zones take
priority. Moving an event clears its previous inferred zone and resolves against
the new coordinates. `timezone_inferred` distinguishes location inference from
publisher data; `publisher_timezone` is not modified. UTC start/end timestamps,
IDs, canonical URLs, and date-only events are unchanged. Identified online-only
events are excluded. Missing coordinates remain unresolved. No city guesses or
network requests are performed. Reads use stored `external_events.timezone`.

Release backend migration first, then collector. Cron begins gradual backfill.
Check cache counts and sample inferred rows against unchanged timestamps and
public markup. Exact coordinate keys allow venue reuse without boundary rounding.

Licenses: timezonefinder code is MIT; timezonefinder-data is ODbL, derived from
timezone-boundary-builder/OpenStreetMap. Retain package license and attribution
files. Sources: https://pypi.org/project/timezonefinder/9.2.0/ and
https://github.com/evansiroky/timezone-boundary-builder .

Python checks cover nationwide locations, DST, invalid/ocean/overlap points,
claim/finish, and no lookup when no work exists. SQL fixture checks run on
PostgreSQL 16.2 with stubbed point accessors, not a full PostGIS/live rehearsal.
They cover cache reuse, immutable instants, source precedence, moved events,
date-only/online exclusion, negative results, authorization and replay rejection.
