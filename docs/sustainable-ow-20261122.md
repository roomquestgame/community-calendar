# Sustainable Oakington and Westwick — November 22, 2026

## Durable source and evidence

The reviewed source is `https://sustainableow.co.uk/feed/`, source key
`municipal_d8e9e58caff75c3b7636fd1d`. Its canonical self-link, channel name and
WordPress site ID `106953790` establish publisher identity. The feed's ten
complete `content:encoded` articles currently span June 4–November 6, 2026.
They contain multiple event sections and duplicate later updates. RSS publication
time is not an event start time.

The original November 6 article is not registered by this change. Normal intake
correctly holds that article and the unadapted RSS as `no_reusable_calendar`:
the article's schema describes an Article, not Event records. Existing generic
WordPress/RSS classifiers are unchanged.

## Exact reviewed adapter

`roomquest/sustainable_ow.py` validates the exact URL/source key and reads only
the supplied complete RSS items. Initial registration reuses its already fetched
response; recurring collection makes one guarded feed GET. No article, archive,
image, external programme or referral is fetched. The ten-item publisher setting,
3 MB payload cap, full-content requirements, exact post identities, consistent
publication/permalink dates and absent pagination form the bounded input contract.
A changed or incomplete feed holds for review. This covers the current rolling
publisher feed; it is not an exhaustive crawl of historical pages.

The reader recognizes the publisher's observed heading/date/time paragraphs,
including date-bearing item titles and separate schedule headings. Titles and
dates are read dynamically. The original publication year supplies context only
when the event omits its year and the dated permalink agrees. Explicit years and
`next year` are honored; old dates are never moved into the current year. Named
weekdays must agree with the resulting calendar date. The normal 60-day occurrence
window and Europe/London rules apply.

Repeated announcements are grouped by event title and date, with the latest
published edition providing the current schedule, narrative and source article
URL. Separate sessions explicitly present in that edition remain separate.
Occurrence IDs are independent of post URLs. A newer explicit TBC schedule
supersedes its older timed duplicate without inventing a time.

Selected event sections require verified times and a reviewed venue. Conflicting
schedule headings/dated paragraphs, another venue or similarly named hall in
another town hold the collection. Monetary decimals cannot supply a clock.
No end is invented where only a start is published.

The current venue contract is `St Andrew's Church Hall`, address
`High Street, Oakington, Cambridge CB24 3AG, United Kingdom`, city `Oakington`.
Only the reviewed Oakington hall aliases map to this address. Coordinates remain
null for the existing geocoder. Sanitized event narrative uses the existing
2,000-character limit. There is no new native-content/media permission, image
candidate or EXIF-derived fact.

## Current result and intentional exclusions

The complete capture produces one future scheduled event: **Christmas Wreath
Workshop, December 9, 2026 at 19:30 Europe/London**, with no published end time.
The latest November 6 post supplies its narrative, including the £3 donation and
all-ages invitation; the October 22 duplicate is not a second event.

Past November sessions remain past. The parenthetical February 6 `next year`
Repair Cafe reminder is an intentionally unscheduled save-the-date, not a timed
event. It remains excluded when it enters the 60-day window until an actual
schedule is announced. Explicit TBC notices, ordering deadlines, ongoing services,
newsletter links and undated external programme referrals are also excluded.
External programme dates are not fetched or inferred.

A valid complete feed with no eligible upcoming scheduled events returns a
healthy empty recurring snapshot. Initial registration still requires an eligible
event: its reviewed-listing gate now explicitly checks the collection result,
retaining `no_extractable_events` for an empty registration attempt. This does
not add a schedule, retry mechanism or source activation path.

## Verification and release boundary

```sh
python -m pytest -q tests/test_sustainable_ow.py tests/test_feed_registration.py tests/test_uk_registered_listings.py tests/test_registered_listings.py tests/test_battersea_bloem.py
```

The focused tests use the actual registration and recurring dispatch, stubbing
only publisher transport and RPC effects. They cover dynamic future events,
all observed section shapes, duplicate updates, explicit year context, correct
clock formats, conflicting facts, wrong venues, complete-empty snapshots,
unscheduled notices, strict feed identity/completeness, deadlines and denials.
Reduced fixtures retain factual scheduling evidence; long narratives are synthetic.
The full captured feed was also replayed offline independently.

The compatibility parser family remains `html` because the reviewed adapter
extracts HTML event sections carried by RSS; it returns the existing
`publisher_event_candidates_v1` contract. The companion backend adds only this
exact feed to its existing reviewed-listing and UK venue helpers. Normal release
and Admin recheck of receipt **879** remain separate steps. Article receipt **878**
remains in review. No other source, classifier, transport, media policy, operational
database row or publication permission is changed by this collector work.
