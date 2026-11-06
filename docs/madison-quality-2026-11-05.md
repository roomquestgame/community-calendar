# Iowa publisher quality and tourism batch — November 6, 2026

Owner-approved backend and collector batch. Companion PRs: RoomQuestGame #628 and community-calendar #71. No mobile GUI changes.

## Included sources and repairs

- Madison WordPress: retain deployed 6–7 p.m. Central schedule and stable IDs; preserve cost; flag the Basket Weaving introduction's conflicting October 6 date without rewriting the original narrative. Aurora's one official inline photo enters the existing candidate-only verified media lane. Basket Weaving has no publisher image and receives no substitute.
- Independence Library: separate the event room label from its repeated street-address suffix.
- Linn MyCountyParks: complete a missing end only when the publisher summary's title, weekday, date and start all agree. Hognose is 10–11 a.m. Central. Classify the reviewed past-trip travelogue as Learn while preserving actual guided outdoor activities and manual overrides.
- Mahaska MyCountyParks: retain the building and explicitly warn about conflicting Lower Level/upstairs room statements. Withhold the month-long travelling exhibit until visiting hours are verified. Registration-option identity continues to use the original published end field.
- Think Iowa City: exact structured WordPress endpoint, local/UTC agreement, bounded pagination, narrative/categories/cost and event-image evidence. Ambiguous multi-day schedules withheld; missing numbered addresses never become city pins.
- UNleash Council Bluffs: three requested calendar months cover sixty days, using each dated event overlay's times, venue, own map address, narrative and event image. No per-event request amplification. Missing clocks, conflicting dates and remote/cancelled listings withheld.
- Visit Mason City: fifteen canonical first-page detail links, three concurrent requests with shared pacing. Visible title/date/clock/timezone must agree with the same event's calendar export. Four publisher DST conflicts withheld. Export-default ends are omitted unless visibly confirmed. First-page omission cannot cancel a known occurrence.

## Read-only publisher evidence

Fresh November 6 UTC review: Think API 134 inputs, 113 timed qualified records (74 numbered addresses; 39 missing addresses), 113 descriptions and 107 image candidates. These are source audit results, not live published counts. Full Council collector fetched November, December and January with HTTP 200: 186 qualified occurrences, each with its own address, description and image candidate. Mason first page: 15 records, 11 qualified; all eleven have event venue/address, narrative and image candidates. Council calendar-download links returned empty/unusable bodies; no independent ICS schedule verification is claimed there. Robots files allowed the reviewed paths; shared request pacing remains enabled.

Clear Lake remains unregistered. Its 368-record ChamberMaster feed includes recurrence children with incomplete metadata/visibility and default end times conflicting with prose. A complete public-occurrence inheritance/time solution is required. Held MyCountyParks Madison 5065 remains pending; the working Madison WordPress source remains authoritative.

## Database and validation

Two guarded migrations extend only exact reviewed sources. The first enrolls Madison in existing identity/staging/completion/photo eligibility/result gates. The second adds a private reviewed WordPress predicate, new-source identity/host contracts, demand-driven publication/geocoding and pending registrations. Discovery centers come from the 2026 Census Iowa Gazetteer and are never event coordinates. Existing shared resolver view entries remain; the frozen legacy cohort is not expanded. The registration migration creates no approval, demand, queues or public events.

Local provider workflow suite: 983 tests plus 33 subtests passed. Fresh isolated PGlite/PostGIS rehearsal overlays the relevant live definitions, applies both final migrations in order, then passes the two new token-staging/publication/media suites and five existing Madison/Independence/parks/community suites. Address-only records wait for resolution then resume with resolver coordinates, repeat publication preserves identity, and paused sources cannot collect. This is targeted local testing, not the native complete live-schema deployment rehearsal. Direct local photo verification was deferred by DNS; live photo success is unverified.

## Release and acceptance

Deploy compatible backend through native validation and guarded Database deploy, then the collector. Keep new registrations pending until deployed collector previews and staged fact checks pass; approve only those reviewed sources. Use bounded operator validation explicitly, never fabricated user search/authentication or cache clock resets. Public publication still requires actual eligible demand. Verify Madison's warning/photo and stable IDs, Linn/Mahaska/Independence refreshes and new-source address queues. Record deployment and acceptance receipts separately; preparation and source audit are not production completion.
