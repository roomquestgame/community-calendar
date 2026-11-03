# MyCountyParks HTML scraper

Beautiful Soup reads the publisher's county event listings and linked detail
pages. The adapter uses the independent `/api/html-demand` family and the
existing transport, staging, classification, address cache and publisher.
Source enrollment is in the companion RoomQuestGame migration. The four initial
sources are pending until deployment and source activation are verified.

## Pilot sources

| Source key | Canonical calendar |
| --- | --- |
| `mycountyparks_ia_story` | https://www.mycountyparks.com/County/Story/Events |
| `mycountyparks_ia_linn` | https://www.mycountyparks.com/County/Linn/Events |
| `mycountyparks_ia_johnson` | https://www.mycountyparks.com/County/Johnson/Events |
| `mycountyparks_ia_iowa` | https://www.mycountyparks.com/County/Iowa/Events |

All use `kind=html`, `platform_adapter=html`, `America/Chicago`. Madison is not
enrolled because its direct WordPress calendar already supplies events and
requires an explicit overlap check. The directory helpers know the publisher's
county names; collection authorization is restricted to the four pilot keys.

## Run a read-only scrape

From the repository root, with Python 3.12 and the pinned requirements installed:

```sh
python scripts/scrape_mycountyparks.py --county iowa --output iowa-events.json
python scripts/scrape_mycountyparks.py --county johnson --timeout 120
```

The output contains normalized JSON records; without `--output`, JSON goes to
standard output and diagnostic messages go to standard error. This command
does not connect to the database or stage, geocode, approve or publish anything.
The timeout is a whole-source deadline (10–300 seconds). Production supplies
the existing shorter HTML worker deadline. DNS/HTTPS checks, robots rules,
per-host pacing, bounded response sizes and exact publisher hosts are enforced
through the same `fetch_publisher` used by the worker.

The `RoomQuest Provider Tests` workflow also has an optional manual
`mycountyparks_live` input. It runs all four pilots with a 30-second per-source
budget and no database credentials. Ordinary regression runs remain offline.

## Extraction contract

- Query the county GET route with `EventSearchModel.CountyName`, `StartDate`,
  `EndDate` and `PageNumber`. The date window is the current Iowa date through
  60 days ahead. No login, browser, POST session, statewide poll or new timer.
- Validate the county, event origin and numeric ID, listing counts, page totals,
  distinct IDs and detail header identity. An unrecognized page or missing page
  is an error, not a healthy zero-event result. Empty results require matching
  county identity and an explicit zero count.
- Bound collection to four 25-record pages and 25 eligible detail requests.
  Exceeding either limit or the deadline fails the source snapshot. Future
  expansion beyond those bounds needs an explicit fetch-continuation design;
  the present publication batches already use the shared continuation path.
- Filter ended events, permit/membership products and canceled titles before
  detail fetches. Check the description for actual cancellation as well; a
  refund policy, full class or closed registration is not itself cancellation.
- Use the listing's start/end schedule and check it against the detail header.
  Interpret local wall times in `America/Chicago`; reject ambiguous or
  nonexistent DST times and unverified overnight ranges. Missing ends remain
  null. Only this adapter opts into retaining an ongoing event until its end,
  or three hours after its start when the end is missing.
- Read the actual Location street address. Always leave coordinates null for
  the existing address cache/Geocodio path. County discovery anchors must never
  become event pins. One missing address may be withheld; an all-unresolved
  source is an error. Diagnostics identify withheld event IDs.
- Preserve source IDs and distinct session times. Combine only explicitly
  labeled carving-tool registration alternatives at the exact same venue and
  time. A group keeps its identity if one option disappears. Preserve prices,
  status and original registration URLs in the persisted description.

## Publisher evidence checked on November 3, 2026

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

Local cached-page tests establish parsing, not production network access.
The implementation workspace cannot resolve publisher hosts through the
guarded socket resolver; it does not disable that check to claim a live pass.
Verify the optional live run, deployed collector, source registration, shared
geocoding and normal area-search publication separately before calling a pilot
visible in EventQuest.

## Regression checks

```sh
python -m pytest tests/test_mycountyparks.py tests/test_mycountyparks_integration.py tests/test_publisher_robots_cache.py -q
```

The normal provider workflow also runs existing HTML, ICS, WordPress,
Squarespace, JSON-LD, demand/staging and transport regressions. Backend SQL tests
cover pending-source inertness, source demand, address continuation, ongoing
visibility and complete/failed/partial snapshot reconciliation.
