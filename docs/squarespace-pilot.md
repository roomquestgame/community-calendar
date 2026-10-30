## Selected Squarespace JSON calendars — October 30, 2026

Ben approved Frazier History Museum and Mission Garden only, following the
nine-endpoint evaluation. Waimea Valley, Avondale, Buffalo and the three library
endpoints are outside this batch. The collector reads the public JSON response
directly; no HTML scraping or per-event detail requests are added.

The adapter admits exactly the two reviewed URLs, verifies publisher timezone,
retains stable IDs, event links and source start/end timestamps, and uses the
existing 60-day window and private staging RPCs. Frazier's past-archive cursor is
accepted only when it matches an explicitly past record; an unknown cursor fails.
Intake is bounded to 100 upstream records, matching the existing staging batch.
Unpublished, cancelled and all-day records are excluded. Event-specific address
and marker coordinates are retained only with a complete in-state street address
and coordinates within the source's reviewed state bounds. These bounds detect
obvious conflicts; they are not independent street-level geocoding. Missing or
conflicting coordinates are held without a substitute pin. Off-site Frazier
locations, including Copper & Kings, retain their own address and coordinates.

Direct publisher JSON snapshots produced 10 Frazier and 6 Mission Garden events
inside 60 days, all 16 with source-provided coordinates. Mission Garden's other
two upcoming records fall outside that window. No descriptions or images are
copied into staging. The two-source data migration reuses Metros5 URL-derived
keys, so applying its older catalog later cannot duplicate the sources. Only
these two JSON rows are approved; other Metros5 feeds retain their existing state.
Source timezone is explicit; publisher rights remain unreviewed and default pins
remain absent. The existing collector handles previews; no Cron, geocoder cohort
membership or publication scope is expanded.

Local validation: 106 Python tests plus 10 subtests passed, py_compile and
git diff --check passed. The full local PostgreSQL/PostGIS migration replay and
provider/staging/discovery suites passed, including the updated Metros5 source
selection assertions. Final-head CI and the fresh production-schema release
gate remain required. The protected transport has not been verified end-to-end
against these publishers from a deployed worker.

Deployment is still blocked by the previously recorded unrelated pending
migration history. No database write, collector deployment, live private intake
or public event publication was performed for this batch. Merge and deploy are
separate from actual map visibility; do not report these 16 events as live.
