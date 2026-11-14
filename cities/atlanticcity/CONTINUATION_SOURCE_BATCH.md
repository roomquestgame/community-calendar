# Atlantic City continuation — November 14, 2026

Ben authorized continued Atlantic City discovery, source integration and production publication. This batch builds on **18 completed calendars and 627 active public occurrences** measured before enrollment. Visit Atlantic City is the nineteenth registered calendar and remains paused after HTTP 403.

## Eight additional direct sources

| Publisher | Captured eligible occurrences | Collection |
| --- | ---: | --- |
| [Margate City Public Library](https://www.margatelibrary.org/events/rss/feeds?per_page=100) | 27 | Bounded native publisher data |
| [Greater Atlantic City Chamber](https://business.acchamber.com/api/events) | 4 | Bounded native publisher data |
| [Jewish Federation of Atlantic and Cape May Counties](https://jewishbytheshore.org/wp-json/tribe/events/v1/events/) | 108 | Durable complete-only manifest |
| [Jewish Family Service of Atlantic and Cape May Counties](https://www.jfsatlantic.org/events/) | 2 | Durable complete-only manifest |
| [Hard Rock Cafe Atlantic City](https://cafe.hardrock.com/atlantic-city/event-calendar.aspx) | 37 | Durable complete-only manifest |
| [Garden State Beer Company](https://gardenstatebeerco.com/whats-happening%3F) | 8 | Bounded native publisher data |
| [Atlantic Cape Community College public events](https://events.atlanticcape.edu/) | 36 | Bounded native publisher data |
| [EHT Nature Reserve Turkey Trot](https://runsignup.com/Race/NJ/EggHarborTownship/EHTNatureReserveTurkeyTrot5k1Miler) | 2 | Bounded native publisher data |
| **Total** | **224** | Production counts must be verified separately |

The [captured audit](../../docs/evidence/atlantic-city-continuation-captured-20261114.json) records exact source identities, dates, venues, narrative lengths and hashes, transport limitations and the overlap review. These are parser expectations, not a claim of 224 published events.

## Collection decisions

- Margate uses complete Stacks RSS bodies. Five native detail comparisons establish that this publisher's RSS publication timestamp is the event clock. Closure intervals suppress overlapping library programs. Wednesday Tai Chi moved to the Martin Bloom Pavilion; Friday remains at the library.
- The Chamber uses its permitted public XML API. Robots-disallowed search and rendermode endpoints are not used. Two weekday/date conflicts and blank job-fair narratives remain held.
- Jewish Federation collects every native API page, then verifies each page hash in a second pass. Changed ordering or content resets the entire manifest. Ordinary public religious programs remain eligible; private board sessions, virtual programs and insufficient location/clock evidence do not.
- JFS follows the accessible current calendar and complete detail bodies. Its blocked API/ICS/next-month paths are not used. Its two events do not duplicate the eligible Federation or Oceanside rows.
- Hard Rock Cafe uses native ICS only for its manifest; full detail prose and explicit clocks control accepted records. Stable native event ID plus date replaces generated unstable UIDs. The venue is the Cafe at 1000 Boardwalk. Changed status, clock or venue fails the snapshot; unsupported recurrence fields are rejected.
- Garden State decodes publisher-linked JSON data without executing scripts. Only explicitly dated manual event widgets are accepted. Equal start/end clocks fail instead of creating a fabricated 24-hour occurrence.
- Atlantic Cape uses full Localist narratives and explicit public eligibility. Public community gaming is included even when tagged Student Life. Both visible and structured streets must match the reviewed campus location. Private, virtual, away-game and conflicting venue records are held.
- The EHT Turkey Trot includes separate 5K and one-mile walk registration identities. Organizer directions and the official reserve location support the entrance at 318 Zion Road. Shuttle parking at 391 Zion Road stays in the description. An automatically generated finish time is omitted.

All sources preserve full normalized descriptions through the existing 12,000-character cohort path. Four captured descriptions exceed 2,000 characters. Missing text is not replaced with a generated synopsis. Coverage circles select source calendars and never supply event coordinates.

## Two existing source recoveries

**Historic Smithville:** Girls Night Out on December 10 has an explicit 10 AM listing clock and 9 PM detail finish. The complete listing and detail narratives support one additional occurrence. Breakfast with Santa remains held for lack of a published start clock.

**Atlantic City municipal calendar:** Third Ward Document Shredding on December 12, 9 AM–noon, retains the residents-only condition. New Jersey OGIS resolves 1800 Marmora Avenue at score 100 to a street-address point along the 1800–1832 range. The visible venue says **“1800 Block of Marmora Avenue (approximate map location)”**. This is a reviewed approximate block destination, not a verified event GPS point. Venue-point contract version 2 invalidates older parser checkpoints.

Both are refreshed through the ordinary source worker. No event row or geocoder cache is injected directly.

## Duplicate review

All 224 captured records were compared with 948 active public events within 50 miles. No confirmed duplicate required suppression. Thirty-one loose candidates were reviewed for actual venue, time and participation differences.

Hard Rock's same-time November 14 FREESTYLE and POOH offers have different qualifying tickets and are retained as separate eligibility-specific promotions. The 5K and one-mile nature walk have different native registration IDs and are separate activities. Library story times and Tai Chi classes at different libraries remain separate occurrences.

## Release and limits

Deploy the matching collector first, wait for production READY, then merge and deploy the eight-source enrollment migration through the existing manual Database deploy workflow. Exact source helpers, description capacity and three checkpoint profiles are extended with drift guards. The completion trigger is extended without replacing existing profiles. No global checkpoint limits, credentials or RPC grants change.

**114 focused tests passed.** They include full narrative retention, publisher clocks, venue conflicts, native identities, cancellations, recurrence rejection, complete-only checkpoints and actual category-worker routing. The integration tests caught and fixed missing collection-context routing for the three new checkpoint calendars. No routine CI or per-source workflow is introduced.

Jewish Federation's API returned HTTP 200 in research, but its robots request returned 520. Normal production guarded transport must decide whether collection can proceed; no bypass is added. Visit Atlantic City's listing still returns 403 and remains paused.

Final deployed source health, public IDs, prose equality, pending locations and counts are recorded in the application repository's Atlantic City continuation production evidence.


## Production collection and reviewed venue follow-through

Collector PR #213 and backend PR #915 deployed successfully. Database run [43640534946](https://github.com/roomquestgame/RoomQuestGame/actions/runs/43640534946) enrolled all eight profiles. Production exposed a missing `Pike` street type in the backend normalizer; the narrow correction in backend PR #916 deployed through [43640988823](https://github.com/roomquestgame/RoomQuestGame/actions/runs/43640988823), with positive/negative postconditions and all 480 migration versions verified.

All **224 captured occurrences now match production staging exactly** in identity/start, complete description hash, full street, event URL and end time. At 21:07:47 UTC, 159 were public; the two recovered old-feed occurrences were also live, yielding **788** across the full cohort. The remaining 65 waited on nine specific venue locations. These timestamped intermediate counts are not the final production total.

The [nine-point official location review](../../docs/evidence/atlantic-city-continuation-reviewed-venue-points-20261114.json) resolves those exact source/name/address tuples using score-100 NJ OGIS matches and publisher corroboration. Four street-interpolated matches receive a visible approximate-map qualifier; address-point matches do not claim rooftop or surveyed-entrance precision. No source-wide fallback is added. Library/community checkpoint contract 2 invalidates old location state and verifies the exact approved point/label on resume.

The venue correction passed **61 focused tests and 36 subtests**, with no whitespace defects. Independent coordinate/order/scope review found no blocker. After collector deployment, only Margate, the Chamber, Federation and Garden State need ordinary source refreshes; no event or geocoder cache is injected. Final publication receipts are maintained in the [application continuation report](https://github.com/roomquestgame/RoomQuestGame/blob/main/docs/evidence/atlantic-city-continuation-production-report.md).
