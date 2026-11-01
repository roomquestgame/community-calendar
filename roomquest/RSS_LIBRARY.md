# WordPress MEC RSS and Library intake

Ben approved the remaining nine non-ICS community registrations on November 1,
2026. Five MEC RSS feeds route to the WordPress family; three Communico/Libnet
JSON feeds and Pima Bibliocommons RSS route to Library. The exact source-key,
URL, kind and adapter registry is in `community_formats.py`. Original source
identities and catalog attribution stay unchanged.

One registered response is fetched through existing public-DNS, HTTPS, robots,
body-size and deadline guards. No detail crawl, new schedule, quota increase,
geocoder, classifier or separate public event store. WordPress Tribe JSON,
Squarespace, JSON-LD, ChamberMaster, direct providers and ICS remain unchanged.

MEC uses explicit startDate/startTime; Library RSS accepts explicit xCal or RSS
Event module times. `pubDate` is never an event start. Missing times/identities,
unknown shapes, conflicting occurrences, explicit pagination, unsafe XML and
oversized snapshots fail into review. Date-only entries are held; no midnight
is fabricated. RSS is the publisher's available feed snapshot, not a claim of
exhaustive website or recurrence coverage. Absence does not infer cancellation.
Libnet refreshes the hard-coded request date in the configured calendar timezone
on every fetch while preserving all original filters and the thirty-day window.
Its array must remain below 500 records; large calendars need a separately
verified partition/pagination contract before release. There is no silent cap.

The same factual normalizer retains event-owned venue/address/GPS, occurrence
identity and category labels. Existing downstream validation and source-scoped
location caches decide publication. Missing locations stay unresolved, never a
library headquarters pin. Successful empty feeds remain healthy. Normal staging
checkpoints must all succeed before preview completion.

The companion app migration queues one validation of only untouched original
research registrations. Manual changes, attempted/reviewed sources and restricted
rights remain paused. Robots denial deactivates with its reason; other failures
or nonempty wholly unlocated snapshots pause for explicit review. Individual
unlocated events stay held while located records can publish. Existing event
IDs, overrides, saved links and referenced-event retention stay unchanged.

Local verification: parser/dispatch/SSRF-registry/bounds/checkpoint tests plus
existing provider suites; isolated 193-migration replay and shared publication,
identity/cache/disposition suites. Native PostgreSQL CI and the guarded fresh
live-schema DB rehearsal remain release gates. Public publisher probes from the
workspace timed out or were inaccessible; fixture success does not establish
that all nine publishers currently match these formats or have usable venues.

Release order: tested collector GitHub main first, verify Vercel READY, then
Database main migration 20261101234024. Inspect each actual validation outcome
and public rows afterward. All nine were paused/idle with no preview or staged
facts at audit time. No recovered feed count or new public listing is claimed.
