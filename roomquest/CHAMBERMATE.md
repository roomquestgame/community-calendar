# ChamberMate public events

`chambermate.py` implements ChamberMate's public JSON calendar as an independent
adapter under the existing municipal source registry, staging, and source-scoped
publisher. The demand channel and `platform_adapter` are `chambermate`; transport
`kind` is `json`. Catalog provenance remains source-registration metadata.

This follows [EVE-6](https://linear.app/eventquest/issue/EVE-6),
[EVE-7](https://linear.app/eventquest/issue/EVE-7), and the implementation issue
[EVE-8](https://linear.app/eventquest/issue/EVE-8/add-a-demand-driven-chambermate-adapter-with-clarksville-pilot).
ChamberMaster/GrowthZone retains its separate XML/iCalendar adapter.

## Registration and demand

The Clarksville pilot source key is `chambermate_clarksville_va`, with timezone
`America/New_York`. Its canonical registry URL contains only tenant identity:

```text
https://api.chambermate.com/core/biz/webPresence/getEventsInfo?websiteShorthand=clarksvillelakecountrychamber&websiteDomain=clarksvillelakecountrychamber.chambermate.com
```

The publisher page is
[the chamber's standalone calendar](https://clarksvillelakecountrychamber.chambermate.com/standalone?id=2716e0c5-6759-608c-30a5-cf824a7ae04a),
linked from [the official events page](https://clarksvilleva.com/events/).
The separate WordPress festival sections are outside this adapter's scope.

The same parser supports other reviewed `tenant.chambermate.com` calendars.
It binds `websiteDomain` to `websiteShorthand + '.chambermate.com'`, allows only
the exact public API path, and rejects unknown or duplicate query parameters.
Custom-domain tenant mappings require a separately reviewed extension. Optional
publisher URLs must use the same tenant host. Every event link must use that
host's `/event-detail?e=<activityKey>` route and match the event's exact ID.

The existing `/api/category-demand` endpoint accepts only a category and a
database-issued one-use ticket. Claims, source ownership, two-hour real search
interest, rights/review holds, leases, retries, shared limits, and publication
continuations stay database-owned. This change adds no timer, source-ID or URL
request input, browser credentials, geocoder, classifier, or publisher. A retry
does not create demand; an `action=publish` continuation does not fetch again.

## Public API and completeness

Each source claim makes one JSON list request. The adapter adds:

- `isPortal=false` and `includeCategories=true`;
- all three repeated `eventTypeCodes`: `CHMBR`, `MBR`, `COMM`;
- `includePastEvents=true`, with explicit UTC `startDateTime=now` and
  `endDateTime=now + 60 days`;
- `rowCount=501`, with a maximum accepted snapshot of 500 parent events and
  500 explicit event occurrences in total.

Read-only verification showed that the date filter includes overlapping events
that have already started, and `eventsCount` reflects that date window before
the row cap. Host-type filtering does not reduce `eventsCount`, so requesting all
three host groups is required. Returned row count must equal `eventsCount`;
missing counts, incomplete/oversized responses, error envelopes, and conflicting
occurrences fail visibly before staging. A valid empty response is distinct
from a fetch or parse failure. Responses never supply another fetch URL.

The shared transport performs public HTTPS/DNS checks, restricts redirects to
`api.chambermate.com`, respects robots and publisher pacing, and bounds the body
to 3 MB. One cold robots preflight may precede the list request; robots rules are
cached for five minutes. There are no per-event detail or image requests and no
adapter retries. The adapter has a 20-second phase budget within the existing
39-second category-processing deadline, and the preview router reserves time
for shared staging. The existing 20-row staging batches must all succeed before
the snapshot can be marked complete or published.

## Event facts and location

The public frontend appends `Z` to API timestamp strings before display. The
adapter therefore interprets timezone-free `startDateTime` and `endDateTime` as
UTC, while retaining the reviewed display timezone. The pilot reports
`EST5EDT`, mapped to `America/New_York`. A changed/unresolved publisher timezone
requires review.

An event keeps its exact `activityKey` and original matching event-detail URL.
Explicit `daySchedules` yield only their published start/end pairs; the parent
range and `noEndTime` flag do not overwrite those intervals or invent intervening
days. Distinct starts share the original activity ID through the existing
occurrence identity. Identical pairs deduplicate; conflicting ends for one
ID/start fail. Each occurrence uses the shared 60-day and ongoing-event lifetime
rules. Date-only `noTimes` events remain an explicit unsupported-time hold.

`In Person` and `Hybrid` retain only the event's own structured address. The
`addressCode='Freeform Custom Text'` discriminator gives `customAddress`
precedence over any stale structured address; its text is retained without
guessing a city or coordinates. `Online` and `Phone` have blank physical venue,
address, city, latitude, and longitude, with explicit `attendance_mode` and
reason metadata. Organizer associations, chamber headquarters, and source-area
centers never supply a pin. Physical locations flow through existing reviewed
evidence, cached coordinates, and the bounded shared Geocodio process. The
companion backend must persist attendance mode and exclude online/phone records
from physical venue resolution and geocoding.

Descriptions use bounded plain `eventFullDescription` or `eventDescription`
(maximum 2,000 characters) as evidence for the existing publication/classifier
path. The existing manual overrides remain authoritative. Event images are
candidate URLs derived from the public event card's explicit storage key:
`https://api.chambermate.com/core/app/storage/directView?k=EVENT/<uuid>`.
The media pipeline owns subsequent byte validation and availability; a candidate
URL alone is not proof that a published event will display that image.

## Publisher categories

The API's `eventCategories.systemFieldOptions` maps each `systemFieldOptionKey`
to `systemFieldOptionLabel`. Each event's
`eventCategoriesSystemFieldOptionKeys` selects its actual labels. These are
preserved individually in `publisher_categories` (up to 20 labels of 100
characters each), including labels containing commas. Missing mappings,
conflicting labels, and over-limit evidence fail instead of silently discarding
labels. The legacy `category` text remains a bounded join for compatibility.

The raw `publisher_event_type` (`CHMBR`, `MBR`, or `COMM`) is retained separately.
Those host groups are not topical categories. No label or EventQuest category is
inferred when the publisher supplies none; the normal classifier and manual
override workflow own that decision.

## Verification

`tests/fixtures/chambermate_clarksville_public.json` preserves the factual public
response shape captured on November 3, 2026, with nine events. Contacts,
registration links, and publisher descriptions are omitted from this fixture;
the online organizer's public address remains to test that it is never a venue.
The initial bounded 60-day window has eight events: seven physical and one online.
The January 12, 2027 event is outside that initial window.

Focused tests cover tenant/URL binding, UTC interpretation, complete-snapshot
counts, independent category labels, descriptions, all four attendance modes,
freeform-address precedence, exact multiple schedules, shared occurrence limits,
existing ticket dispatch, all-batch staging, failed-snapshot nonpublication, and
publication continuations without a refetch:

```sh
python -m pytest tests/test_chambermate.py tests/test_chambermate_integration.py tests/test_category_worker.py tests/test_category_entrypoint.py -q
```

The provider CI workflow includes both ChamberMate test files. Code and local
tests do not approve a source or prove deployment/publication; release and live
normal-search verification remain coordinated with the application registry and
shared backend migration.
