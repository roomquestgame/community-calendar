# Communico event pages instead of ICS downloads — November 23, 2026

Ben reported that the source button for **Kid's Cafe, Whitney Library**
downloaded a calendar. His follow-up confirms multiple affected listings.
The live occurrence identified by the parent audit has publisher UID
`17130479`, source `municipal_mapsee_31a9e5bbfb8129a494d7b883`, and starts
`2026-11-23T22:30:00Z`. Its public URL was the registered `/feeds?data=...`
iCalendar export instead of the publisher's `/event/17130479` page.

## Cause and correction

The shared ICS normalizer preserves a valid VEVENT URL but falls back to the
registered feed when that field is absent. Communico exports expose a numeric
publisher event UID; the existing `santa_cruz_libnet` adapter already uses that
UID as its `/event/{id}` page identity. The Library District's official indexed
pages also use this format, for example
<https://events.thelibrarydistrict.org/event/17130468> for the November 12
Whitney program. This change reuses that native platform identity.

`roomquest/communico_links.py` requires all of the following before supplying a
page: HTTPS, an accepted Communico hostname, the exact `/feeds` endpoint, a
single valid base64 JSON `data` parameter with `feedType=ical` and a `filters`
object, and an original numeric VEVENT UID of 5–10 digits. The host is either a
single tenant of `libnet.info` or the reviewed custom host
`events.thelibrarydistrict.org`. Credentials, alternate ports, fragments,
ambiguous queries and unrelated hosts are rejected. Explicit non-feed event
URLs retain precedence. Other ICS providers retain their current fallback.

The shared adapter applies this before its legacy/new-source branch, using the
original UID to preserve recurrence expansion identities. It changes only the
event URL; the source registry, times, venue facts, descriptions, images,
classification and publisher-access policy are unchanged. There are no extra
publisher requests and no new per-event fetching. All eleven registered
Library District feed groups meet the same platform contract.

## Incremental collection

The existing `parser_context()` hashes all deployed `roomquest` Python files,
so this adapter/helper change automatically invalidates old normalized parser
evidence. Event hashes also include `event_url`; a link-only edit is staged as
changed and requests publication. Ordinary ICS feeds are fully parsed on their
moving window. Raw-feed HTTP 304 reuse is deliberately disabled; the existing
conditional normalized-detail path is limited to ChamberMaster details.

## Validation and release handoff

Based on collector main `e051987cf01fe96349f7ab20152cac7c39e0f7a8`, the focused
offline command passes **133 tests**:

```sh
python -m pytest -q tests/test_communico_links.py tests/test_ics_family.py tests/test_incremental_snapshot.py
```

Coverage includes the seven reported branch occurrence identities, all eleven
registry feed groups, both shared parser modes, preserved explicit links,
invalid host/feed/UID cases, recurrence identity and actual Mapsee dispatch with
one mocked feed fetch. Existing Duke fallback and incremental collection cases
pass. The incremental regression confirms link-only edits restage while
unchanged events retain their fast path. `git diff --check` is clean. Fixture
times and event narratives are synthetic; this is not a claim of a live feed
refetch. Local and search-tool requests to the official Library District page
and feed returned HTTP 403, which was not bypassed.

Normal release is a reviewed collector PR, merge to main, and verified Vercel
production READY at the merged commit for team `room-quest-game`, project
`roomquest-community-collector`. The runtime changes qualify for its existing
build selector. No routine GitHub CI label, check or manual test workflow is
required. The parent owns release and the eleven ordinary Admin Preview
refreshes, then stored/public URL readback. No production write, deployment or
public acceptance is claimed by this local preparation.

The companion application change handles free meal program classification.
There is no source enrollment or database migration in this collector patch.
