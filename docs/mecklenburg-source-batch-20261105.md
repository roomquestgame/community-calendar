# Mecklenburg County reviewed collector batch

Prepared for [EVE-39](https://linear.app/eventquest/issue/EVE-39/deploy-a-mecklenburg-area-source-batch-with-verified-venues-and-feed).
The publisher captures were checked on November 5, 2026 in America/New_York
(November 6 UTC). This change prepares Rosemont and Chase City for the existing
collector and retains the library parser work dormant behind a robots check.
The release has two eligible active sources and one held source. Source
registration, demand coverage, protected publication and
verified geocoding belong to the companion application migration. Local parser
results are not evidence of production ingestion or public map visibility.

## Source contracts

| Source key | Reviewed endpoint | Adapter | Parsed candidates | Release status |
| --- | --- | --- | ---: | --- |
| `mecklenburg_va_libraries` | `https://calendar.google.com/calendar/ical/mecklib.org%40gmail.com/public/basic.ics` | `kind=ical`, `platform_adapter=ical` | 25 | Held: paused, disabled, routing disabled |
| `rosemont_of_virginia` | `https://rosemontofvirginia.com/wp-json/tribe/events/v1/events` | `kind=json`, `platform_adapter=wordpress` | 3 | Eligible active source |
| `chase_city_chamber_va` | `https://chasecitychamber.com/upcoming-events` | `kind=html`, `platform_adapter=html` | 1 | Eligible active source |

The captures yielded 29 parsed candidates; only four belong to the two sources
eligible for active registration. The 25 library candidates remain offline
evidence and must not be collected or published under the current robots policy.

All three retain actual occurrence dates, publisher attribution and original
links. Narratives for these reviewed sources are capped at 2,000 characters.
No source-wide map pin, new scheduler, geocoder subscription, separate events
directory or native event is introduced. Off-site event addresses remain off-site.

### Mecklenburg County Public Library

**Activation is held.** A subsequent live request to
[`https://calendar.google.com/robots.txt`](https://calendar.google.com/robots.txt)
returned HTTP 200 with exactly:

```text
User-agent: *
Allow: /$
Disallow: /
```

These rules deny the exact library iCalendar path, and the existing robots parser
also returns false. No calendar request was made after establishing this denial.
The dispatcher now uses `respect_robots=True` for this exact library source key,
so a robots denial stops the calendar HTTP request and parsing. Other legacy ICS
sources keep their existing transport behavior. The companion registration must
remain paused and disabled, with discovery routing disabled. The parser work
below is retained dormant; the public feed's prior HTTP 200 is not permission
to activate automated collection.

The library [official calendar](https://www.youseemore.com/mecklib/calendar.asp)
links its shared Google iCalendar feed. The
[official directory](https://www.youseemore.com/mecklib/directory.asp) supplies
four reviewed branch identities:

| Branch | Address |
| --- | --- |
| Boydton Public Library | 1294 Jefferson Street, Boydton, VA 23917 |
| Burnett Library & Learning Center | 914 Virginia Avenue, Clarksville, VA 23927 |
| R. T. Arnold Public Library | 110 East Danville Street, South Hill, VA 23970 |
| Butler Memorial Library | 515 Marshall Street, Chase City, VA 23924 |

The exact source key and feed URL enable a bounded archive optimization. After
the original raw-component and recurrence-shape validation, the adapter removes
only provably expired timed UID groups with an explicit UNTIL, a resolved end,
and no future override, RDATE, EXRULE, competing master or RANGE exception.
COUNT-only and date-only rules stay on the original path. The existing raw
component, active-master, normalizer and output limits remain. This prevents old
archive series from consuming the active recurrence budget without weakening
the budget for other sources or future occurrences.

An observed branch LOCATION may use its reviewed directory address. An omitted
LOCATION is resolved only for four exact, unchanged series UID-and-title pairs
listed in `ics_adapter.py`. Changed/unknown series stay unlocated, and supplied
off-site locations and coordinates remain intact. No branch coordinates are
invented. Original UIDs, occurrence identities, exception dates and moved
occurrence details survive normalization.

Publisher `Closed` records are closure intervals, not public activities. Their
overlapping occurrences are withheld for review, respecting branch scope and
exclusive date-only ends in America/New_York. The observed December 24 storytime
conflicts with the system closure and is withheld; the remaining local sample
contains 25 activities. Missing timed closure ends are not guessed.

Actual occurrence descriptions are retained, including overrides. Events without
an event-specific URL link to the real official shared calendar above, never a
fabricated detail page. Current candidates contain no images. The library stays
on the existing ICS finish lane; this batch does not approve arbitrary image
hosts or use shared calendar-page artwork as an event image.

### Rosemont of Virginia

Both the public TEC JSON endpoint and the
[official calendar export](https://rosemontofvirginia.com/events/?ical=1)
returned 11 matching listings. JSON is the selected runtime route. Publisher
[robots.txt](https://rosemontofvirginia.com/robots.txt) allows the endpoint.
The existing WordPress collector retains its 60-day query, maximum five pages,
100 raw records per page, 500-record bound and worker deadlines. Response next
links are never followed; requests are rebuilt on the registered host.

Only this exact source gains narrative and publisher-image evidence retention.
Published, visible, timed, physical public listings are eligible. Explicit
Closings categories, closure notices, private/member-only listings and cancelled
or postponed entries are excluded. UTC and local timestamps must agree with the
publisher's America/New_York timezone.

The reviewed sample retains:

| Publisher ID | Event and local schedule | Actual venue |
| --- | --- | --- |
| 7745 | Wine + Dine w/Short Stacked; November 7, 11 a.m.–5 p.m. | Rosemont, 1050 Blackridge Road, LaCrosse, VA 23950 |
| 7988 | Wine Dinner at Blue Jay Bistro; November 12, 6–8 p.m. | Blue Jay Bistro, 141 E South Main St, Littleton, NC 27850 |
| 8121 | Ugly Sweater Weekend; December 12, 11 a.m.–5 p.m. | Rosemont, 1050 Blackridge Road, LaCrosse, VA 23950 |

The December 13 prose mention does not create a second occurrence. Five closure
or club listings are excluded. Two Up Wine Down Festival (8133) and Books,
Bites & Bonded (7995) have no structured event venue and remain held. The reviewed
November 21 Beer Fed Beef occurrence (7956) is held because its header starts
at 11 a.m. while its service description starts at 1 p.m.; no time is substituted.
Holds are logged and do not declare cancellation. An otherwise empty result
with unresolved held events fails into review instead of claiming a healthy empty.

Public event detail URLs must use the publisher's HTTPS host and
`/event/[a-z0-9-]+/?`, without query or fragment. Image candidates are limited to
that publisher's `/wp-content/uploads/` image files. Logos, avatars, favicons and
pixels are omitted. The current Short Stacked vendor logo is omitted; Blue Jay
and Ugly Sweater supply two image candidates. Candidate presence does not mean
the photo worker has validated or displayed the image.

### Chase City Chamber of Commerce

The registered [normal HTML calendar](https://chasecitychamber.com/upcoming-events)
is fetched once. Its actual 17 cards contain one upcoming event. The adapter
parses the publisher's Google Calendar link locally for explicit UTC timestamps;
it never requests that URL. Those timestamps must match the visible date/time
in the publisher's declared America/New_York timezone. Original event URLs
provide stable source-scoped identities. There is a 100-card ceiling, a 20-second
collector budget, and no detail crawl. Unknown pagination fails into review.

The November 6 [Awards Cocktail Party](https://chasecitychamber.com/upcoming-events/chase-city-chamber-of-commerce-awards-cocktail-party)
runs 6–7:30 p.m. Its structured location is empty. The exact event's flyer names
the Estes Center Banquet Room; the same publisher identifies that named center
at 316 N Main St, Chase City, VA. This reviewed event-specific association is
bound to the exact event URL, title, start, end, image URL and address evidence.
It is not a publisher-office fallback. New or changed events with unknown venues
are held. A changed reviewed flyer or conflicting visible schedule requires review.

The short flyer transcription preserves the actual $25 price, included
refreshments, and October 30 RSVP deadline. It does not claim tickets remain
available. Normal text descriptions are read only from each event card's body;
the title and site footer are never substituted for missing narrative.

Image candidates must belong to this publisher's Squarespace CDN collection
`https://images.squarespace-cdn.com/content/v1/64921bef4a756810ab11ec54/`.
The current exact flyer is the sole candidate. Details evidence uses the actual
event URL; image evidence uses the fetched calendar page where that event card
and image appeared together. No image is downloaded by this collector.

## Publisher evidence and backend handoff

Rosemont and Chase City use the existing `publisher_event_details_v1` and
`publisher_event_candidates_v1` contract, then the existing v3 preview finish
RPC after all staged batches succeed. Evidence contains the real narrative,
location provenance, publisher categories, and explicit cost when supplied.
The image URL remains a candidate for the bounded media worker.

The companion backend must enroll only the named source identities, exact
event URL shapes, image hosts/paths and evidence URLs. It must also allow the
reviewed narratives through staging/publication, preserve actual provider types,
and route factual event addresses through the existing location cache/geocoder.
All four local Rosemont/Chase candidates have null coordinates pending that
verified path. Coarse source discovery coverage must never become event pins.

## Deferred source and robots follow-up

The Chase City and Southern Piedmont Master Naturalists Squarespace robots files
explicitly disallow `format=json` and `format=ical` export paths. Neither route
is enrolled. Normal public HTML remains the Chase City route. The
[Master Naturalists public programs](https://www.southernpiedmontmasternaturalist.org/public-programs)
have no current upcoming programs in the captured sample and remain unactivated.

The existing Python RobotFileParser was observed to treat these wildcard rules
as literal paths and report the exports as allowed. That transport issue is a
separate scoped follow-up. This batch does not exploit it, relax robots handling,
change the shared parser or enable an export route through an alternate URL.

## Verification and release boundary

Focused tests cover real factual snapshots, public/private filters, time and
venue holds, original/off-site identities, recurrence limits and exceptions,
strict source/media scopes, no guessed pins, and staging before v3 finish.
Committed capture fixtures retain publisher facts while replacing unnecessary
prose with explicit synthetic fixture text; the capture manifest records origins.

On the assembled main-based branch, all 34 Python test modules named by the
provider workflow passed: 998 tests and 33 subtests. The five Vercel build-selection
tests also passed. These are offline parser, dispatcher, evidence and worker
regressions before the final library-only robots guard. A subsequent focused
denial test exercises the real fetch path with the captured Google rules and
proves no calendar HTTP request or parser invocation occurs; a companion check
preserves unrelated legacy ICS behavior. The affected final-guard suite passed
126 tests and 22 subtests. The 25 + 3 + 1 counts above come from
separate read-only publisher capture dry runs, not a production refresh.

An attempted real-transport preflight stopped at `validate_public_dns` with
`dns_unavailable` for all three publisher hosts in this local runtime. The DNS
gate was not bypassed. Actual `preview_source` transport has therefore not been
proved here for Rosemont or Chase City and requires a network-capable runner.
The library remains held regardless of that environment limitation because its
raw robots policy explicitly denies the feed path.

The existing label-triggered provider workflow includes both new suites. Keep
the upstream generation workflows and production cadence unchanged. Run local
provider/dispatcher/evidence regressions and validate the final PR head once
with `ci:validate`. A green PR is separate from merge, collector deployment,
companion database release, actual demand refresh and public discovery evidence.

Concurrent collector PR 71 changes Madison evidence in the same three shared
files. It was reviewed read-only while open. No unmerged implementation was
copied. If it lands first, preserve its Madison evidence/finish predicates when
rebasing this source-specific change, then rerun the affected tests.
