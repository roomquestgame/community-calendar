# Raleigh Brewing and Longleaf: complete native event calendars

Reviewed November 15, 2026 as part of one four-source Raleigh continuation
batch with Page 158 Books and Dose Yoga. The existing municipal registry was
checked before implementation; neither source key nor publisher alias was
already registered. Existing working sources and access holds are unchanged.

## Exact registrations and frozen results

| Source | Exact HTML calendar | Accepted occurrences | Held eligible details |
| --- | --- | ---: | ---: |
| `longleaf_hotel_raleigh_nc` | `https://www.thelongleafhotel.com/events` | 17 | 0 |
| `raleigh_brewing_neil_st_nc` | `https://www.raleighbrewing.com/upcoming-events` | 9 | 1 |

Both tuples use `html`, `html`, `America/New_York`. Requests remain on the
respective `www` publisher host. The frozen anchor is November 15, 2026 at
13:45 UTC, with the existing 60-day upcoming/ongoing window. Complete native
descriptions and exact event venue streets are required. A blank body is held;
a body exceeding 12,000 characters is held rather than sliced.

All ordinary robots, listing and detail captures returned HTTP 200. The
research helper retained the RoomQuestCommunityCalendar identity, robots
evaluation, crawl-delay pacing, bounded responses and no redirects. These
observations establish access from that environment at capture time only.
Production must still satisfy the shared worker's independent access checks.

## Longleaf

The Squarespace calendar has 47 native cards, 17 current/upcoming cards and no
pagination. Each current card is followed to its native detail. The parser
requires the exact site, collection and item identities; native calendar
export dates, visible clocks and detail Event JSON-LD must agree. It never
fetches the Google export URL or invents a recurrence.

The 17 records comprise eight explicitly week-long Bottle of the Week
promotions, seven dated Thursday Uncorked wine promotions, one Wes Anderson
film screening and one late-night comedy event. The currently ongoing
November 9–15 interval is retained through its explicit end. The two native
December titles containing `(Copy)` are preserved. A week-long promotion is
one published interval, not seven fabricated daily sessions. Other titles
with an implausibly multi-day duration are held.

Full prose comes from the event's complete Squarespace Post Body, not its
short listing or structured teaser. Every event explicitly names The Longleaf
Hotel and `300 North Dawson Street, Raleigh, NC 27603`. Its native venue point
`35.7842775, -78.64240039999999` is accepted only after the event's own full
street and venue agree with that publisher location. No regional centroid is
used. Owner-specific native Squarespace images are retained when present.

The real saved replay completes in six chunks with 17 accepted records,
no held details and a 35,066-byte final checkpoint.

## Raleigh Brewing: actual occurrences and full detail hydration

The public Wix widget has eight seed cards and explicitly reports no further
listing pages. Four seeds are at the Neil Street venue; four are explicitly
at a different Smithfield venue and are outside this source's Raleigh scope.
The fixed public application, site and instance identities are verified.

Wix exposes only the next instance of each recurring series on the listing.
Detail pages supply a total occurrence count and dated “other dates” links.
Pinecone and Speed Puzzling expose all their announced dates through those
links, including one January date each beyond the current window. Trivia
advertises six dates, but the detail-link graph exposes only four. That graph
cannot be marked complete.

The publisher-emitted events-details controller implements the normal public
`GET /_api/wix-one-events-server/web/events/{event-id}/occurrences` operation.
The exact observed query uses `status=0&status=1&locale=en-US&offset=0` and
ordinary offset pagination. The publisher's anonymous, page-emitted Wix
instance is validated against its app, instance and metasite before use.
It is held only in memory for the request and never enters a checkpoint,
log, repository fixture or production evidence. The transport accepts only
that HTTPS host, exact route, UUID and bounded offset, and cannot be combined
with other credential/header modes. Robots, DNS validation, the honest user
agent, pacing, deadline, JSON content type and size limits remain in force.
A redirect or HTTP rejection stops the request without a retry or new route.

The observed public response returned HTTP 200 and six explicit Trivia
records with `total=6`, unique native IDs and matching per-ID local-date data.
**Its `about` and `description` strings are blank.** It proves dates and
identities only. All six exact native detail URLs, including the newly
discovered December 17 and December 24 pages, are read separately to obtain
the full visible description. Those two additional detail reads returned
HTTP 200 with the same ordinary guarded helper.

The collector follows only native dated URLs. It does not generate weekly
dates from the words “Trivia Night.” Every accepted occurrence verifies its
native ID/series, Event JSON-LD dates/status, in-person location and full body.
The current result is six trivia nights, two Pinecone Bluegrass Jams and one
Speed Puzzling night: nine accepted occurrences. The December 12 karaoke
listing has no native narrative and is held with
`raleigh_direct_description_missing`. Dates after the window are accounted
for but not published in this capture.

Each accepted event supplies `3709 Neil St, Raleigh, NC 27607` and a native
coordinate pair. Both native coordinate representations must agree, and the
event must explicitly name the reviewed Raleigh venue. Smithfield events
never inherit a Raleigh address. Complete descriptions prefer the full visible
About body over a short JSON-LD teaser; a complete standalone description is
used only when no longer native body exists.

The real saved replay completes in five chunks, with nine accepted records,
one blank-description hold, four explicit geography exclusions and a
19,810-byte checkpoint. No anonymous instance is present in that checkpoint.

## Completion and resumption

The `social_v1` completion profile has a 100-item detail manifest, 200-event
cap, 850,000-byte checkpoint cap and three guarded requests per chunk. Partial
chunks expose no events for staging. Completion requires the fully discovered
listing, every queued detail outcome, accepted-record accounting, every
advertised series count and any started native-API pagination to reconcile.
An API's repeated ID, changing total, conflicting native metadata or incomplete
page sequence fails visibly. Full descriptions remain in the normalized data,
while the checkpoint and per-source manifest hashes protect resumable state.

Local verification covers the full saved replays, source and response identity,
description integrity, concrete times and streets, no false-complete 4/6
series, pagination/duplicate rejection, checkpoint accounting and the scoped
transport's access-denial behavior. The batch changes no classifier, shared
cross-provider deduplication or existing source enrollment.

## Unselected discovery

Compass Rose's official events page was accessible, but several cards exposed
only weekday names and no full dates. Some recurring text remained seasonal.
No recurrence was invented and no source was enrolled from that capture. It
remains a prospect requiring a clearer dated calendar or schedule.
