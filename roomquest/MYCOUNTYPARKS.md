# MyCountyParks HTML scraper

Beautiful Soup reads the publisher's county event listings and linked detail
pages. The adapter uses the independent `/api/html-demand` family and the
existing transport, staging, classification, address cache and publisher.
Source enrollment, approval and area-demand scheduling are in the companion
RoomQuestGame backend. Recognizing a county here does not create a job or activate
a source.

## County catalog

The adapter recognizes the 99 Iowa counties in the publisher's
[county directory](https://www.mycountyparks.com/county/default). Every exact
canonical calendar route was checked against a county-identified response on
November 3, 2026. Source keys use `mycountyparks_ia_` plus the lowercase county
name with spaces replaced by underscores and apostrophes removed. For example:

| Source key | Canonical calendar |
| --- | --- |
| `mycountyparks_ia_iowa` | https://www.mycountyparks.com/County/Iowa/Events |
| `mycountyparks_ia_mahaska` | https://www.mycountyparks.com/County/Mahaska/Events |
| `mycountyparks_ia_black_hawk` | https://www.mycountyparks.com/County/Black-Hawk/Events |
| `mycountyparks_ia_obrien` | https://www.mycountyparks.com/County/OBrien/Events |

All use `kind=html`, `platform_adapter=html` and `America/Chicago`. The source key
and full calendar URL must match the catalog exactly; alternative hosts, query
strings, unknown counties and mismatched county URLs are rejected before HTTP.
Backend review decides enrollment and overlap with existing direct calendars.
The collector does not merge unrelated publisher IDs across sources.

Print all canonical source definitions without network access:

```sh
python scripts/scrape_mycountyparks.py --list-counties
```

## Run a read-only scrape

From the repository root, with Python 3.12 and the pinned requirements installed:

```sh
python scripts/scrape_mycountyparks.py --county iowa --output iowa-events.json
python scripts/scrape_mycountyparks.py --county mahaska --timeout 120
```

The output contains normalized JSON records; without `--output`, JSON goes to
standard output and diagnostic messages go to standard error. This command
does not connect to the database or stage, geocode, approve or publish anything.
The timeout is a whole-source deadline (10–300 seconds, default 120). Production supplies
the existing shorter HTML worker deadline. DNS/HTTPS checks, robots rules,
per-host pacing, bounded response sizes and exact publisher hosts are enforced
through the same `fetch_publisher` used by the worker.

An explicit all-county audit uses the same parser and HTTP guards in one process,
sharing robots rules and per-host pacing:

```sh
python scripts/scrape_mycountyparks.py --all-counties --timeout 30 \
  --overall-timeout 900 --output mycountyparks-audit.json
```

This command continues after individual county failures. Its report gives every
county a `complete`, `failed` or `not_attempted` status. Failed or unattempted
sources do not receive a fabricated zero count. The overall `event_count` sums
normalized records from complete counties, after registration options are
combined; the final console summary includes this total. The command exits nonzero if any
county fails or the overall deadline is reached. The default all-county budget
is 30 seconds per county and 900 seconds overall; the maximum overall budget is
3,600 seconds. A verified empty calendar is a successful result.

The `RoomQuest Provider Tests` workflow has an optional manual
`mycountyparks_live` input that runs this all-99 audit with the 30/900-second
budgets and no database credentials. It retains the public JSON report even
when a county fails. Ordinary regression runs remain offline. Neither the CLI
nor the workflow creates a recurring poll or a statewide background timer.

## Extraction contract

- Query the county GET route with `EventSearchModel.CountyName`, `StartDate`,
  `EndDate` and `PageNumber`. The date window is the current Iowa date through
  60 days ahead. No login, browser, POST session, statewide poll or new timer.
- Validate the county, event origin and numeric ID, listing counts, page totals,
  distinct IDs and detail header identity. An unrecognized page or missing page
  is an error, not a healthy zero-event result. Empty results require matching
  county identity and an explicit zero count.
- Bound collection to four 25-record pages and 25 eligible detail requests.
  Exceeding either limit or the deadline fails the source snapshot. These are
  per-county bounds, unchanged by the larger catalog. A higher-volume county
  needs an explicit fetch-continuation design before these limits can grow;
  the present publication batches already use the shared continuation path.
- Filter ended events, permit/membership products and canceled titles before
  detail fetches. Check the description for actual cancellation as well; a
  refund policy, full class or closed registration is not itself cancellation.
- Use the listing's start/end schedule and check it against the detail header.
  Interpret local wall times in `America/Chicago`; reject ambiguous or
  nonexistent DST times and unverified overnight ranges. A published end equal
  to the start gives no usable duration and is treated as missing. Earlier ends
  remain errors. Missing ends stay null. Only this adapter opts into retaining
  an ongoing event until its end, or three hours after its start when the end
  is missing.
- Withhold the observed same-date conflict where the listing says midnight,
  the detail header says noon, and neither has a usable end. Neither time is
  selected as authoritative. The event's county, ID and title must still match;
  every other schedule mismatch remains a source error. Diagnostics identify
  the county, event ID and conflict reason.
- Read the actual Location street address. Always leave coordinates null for
  the existing address cache/Geocodio path. County discovery anchors must never
  become event pins. Preserve published numeric hyphenated house numbers such
  as Mitchell's `1879-3 Highway 9`, along with the full city/state/ZIP checks.
  One missing address may be withheld; a source with no trustworthy records
  because of missing addresses or the recognized time conflict is an error.
  Diagnostics identify withheld event IDs.
- A successful complete snapshot contains the trustworthy records after these
  explicit data-quality exclusions. Complete-snapshot reconciliation may
  withdraw a previously published record that now has this time conflict or
  lacks usable address evidence. Fetch failures, incomplete pages and unknown
  structure/identity errors still fail the entire source snapshot.
- Preserve source IDs and distinct session times. Combine only explicitly
  labeled carving-tool registration alternatives at the exact same venue and
  time. A group keeps its identity if one option disappears. Preserve prices,
  status and original registration URLs in the persisted description.

## Publisher evidence checked on November 3, 2026

- All 99 county calendar routes returned a matching county identity: 34 had
  listings and 65 were explicitly empty in the November 3–January 2 window.
  The bounded listing audit observed 149 cards; the busiest county had 20,
  within the existing 25-detail budget. These are listing observations, not a
  claim that every event has a usable address or completed geocoding.
- [Open Nature Center Saturday, 29872](https://www.mycountyparks.com/County/Iowa/Park/Lake-Iowa-Park/Events/29872/Open-Nature-Center-Saturday):
  the listing gives 10 a.m.–2 p.m. on November 14; the Outlook `.vcs` download
  instead gives midnight UTC for both start and end. Calendar exports are not
  used as schedule evidence.
- [Kayaking at Bender Pool, 29373](https://www.mycountyparks.com/County/Linn/Park/Wickiup-Hill-Learning-Center/Events/29373/Kayaking-Session-at-Bender-Pool):
  the Location block gives Bender Pool, 940 14th Avenue SE, Cedar Rapids, while
  the embedded map coordinates match the parent Wickiup Hill park. The actual
  event address is authoritative for geocoding.
- [Johnson printmaking choices](https://www.mycountyparks.com/County/Johnson/Events):
  IDs 29729 and 29730 offer the same November 13 session with different tool
  choices. Separate sessions and age groups remain distinct.
- [Floyd evergreen workshop, 29962](https://www.mycountyparks.com/County/Floyd/Park/Tosanak-Recreation-Area/Events/29962/Evergreen-Wreath-Porch-Pot-Workshop):
  the November 29 listing gives 2–2 p.m., while the detail header gives only
  2 p.m. The normalized event retains that start and a null end. Its published
  Location is the Learning Center at Tosanak Recreation Area, 2543 Glass Road,
  Marble Rock; no park coordinates supply the event pin.
- Mahaska 29691, Marion 29435 and Marshall 29831 list midnight but display noon
  on their detail pages without a usable end. Their prose describes flexible
  bird counts or a month-long self-guided activity, so it does not establish
  one reliable start. These records are withheld; other verified county events
  can still be collected.
- Mitchell 29817 and 29815 explicitly publish Milton R. Owen Nature Center,
  `1879-3 Highway 9`, Osage, IA 50461. The hyphenated number is retained exactly;
  it is not a missing address and does not supply a verified map pin.

Local cached-page tests establish parsing, not production network access.
Verify the optional live run, deployed collector, source registration, shared
geocoding and normal area-search publication separately before calling a county
visible in EventQuest.

## Regression checks

```sh
python -m pytest tests/test_mycountyparks.py tests/test_mycountyparks_integration.py tests/test_mycountyparks_cli.py tests/test_publisher_robots_cache.py -q
```

The normal provider workflow also runs existing HTML, ICS, WordPress,
Squarespace, JSON-LD, demand/staging and transport regressions. Backend SQL tests
cover pending-source inertness, source demand, address continuation, ongoing
visibility and complete/failed/partial snapshot reconciliation.
