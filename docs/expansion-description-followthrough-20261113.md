# Expansion descriptions: collector and publication follow-through

Ben requested a fresh check of Norfolk, Richmond, and Omaha/Lincoln descriptions.
The earlier market-description patch is deployed, but the live audit found two
remaining failure modes: venue adapters dropped prose from payloads they already
loaded, and the database's separate scheduled queue publisher still wrote null
descriptions. Both need correction before a collector refresh can persist prose.

## Live audit before this follow-through

Captured November 13, 2026 at 22:23 UTC. These are upcoming records grouped by
source coverage centers, including the surrounding region, rather than counts
from a particular app search radius. VA centers are latitude 36.4–38.1 and
longitude −78–−75.5, divided at latitude 37.2; Nebraska centers are latitude
40.4–41.7 and longitude −97.2–−95.5.

| Source cohort | Published upcoming | Blank descriptions | Staged upcoming | Blank staged |
| --- | ---: | ---: | ---: | ---: |
| Norfolk | 947 | 436 | 1,091 | 500 |
| Richmond | 582 | 536 | 596 | 424 |
| Omaha/Lincoln | 1,414 | 606 | 1,577 | 665 |

Mechanicsville Library had 89 staged descriptions while all 87 published
events were blank. CFengage had 12 staged descriptions and ten blank published
events. Omaha Public Library (211 events) and Lincoln City Libraries (277)
already had full nonblank coverage. Short descriptions and repeated program
copy were reviewed as content, not automatically rejected by length.

## Collector changes

- Retain event-scoped Squarespace list descriptions and excerpts, and Eleanor's
  already-loaded detail content. Omit exact title repetitions and content tags.
- Preserve sanitized ICS narrative in Firespring exports, including Lincoln
  Chamber's shared parser.
- Keep the matched offline Meetup event's structured description for Spielbound.
- Keep The Admiral's narrative only from the matched Rockhouse event container.
- Keep SevenVenues detail narratives for every existing showing, Sandler detail
  narratives where the collector already loads them, and matched Event JSON-LD
  descriptions for Prince Books and Flourish.

These changes add no publisher requests. Event IDs, dates, venue checks, source
eligibility, and existing fetch budgets are unchanged. Narratives pass through
the shared sanitizer and its established limit; no generated summaries or title
fallbacks are used.

Captured publisher payload replays recovered useful text for all seven
Pageturners events (144–771 characters), three of seven Saro listings, a Lincoln
Chamber event (273), Eleanor's author event (1,897), The Admiral (2,000),
SevenVenues (917), Sandler (831), and Flourish (135). Saro's title-only and
publisher-empty entries correctly remain empty. These are parser receipts,
not claims that the production records have already refreshed.

## Verification and release

The focused description, adapter, preview, and scoped-RPC suites passed with
61 tests and ten subtests. The workflow now includes both new description
regression files. Cases check event identity, exact structured-event matching,
title-only copy, navigation/sidebar exclusion, and unchanged network counts.

The companion backend change repairs
`rq_curator_private.publish_requested_community(integer)`, including its fast
comparison, insert, and conflict update. Deploy it through the normal database
rehearsal before refreshing affected sources; otherwise later scheduled cycles
can clear correctly collected prose. After both releases, use bounded approved
source refresh/publication requests and compare staged against public records.

## Remaining coverage gaps

Listing-only sources such as Downtown Norfolk, America's Pub Quiz, Lauritzen,
Reverb/Sydney, and some single-show Sandler entries need separately verified
detail extraction when their listings contain no event prose. Nauticus's raw
detail capture returned HTTP 403, so no unverified content traversal was added.
Lynnhaven River NOW needs a refresh to replace old navigation-contaminated text
using the previously deployed cleanup. Blank publisher content must remain
blank; completeness is not evidence that a description is useful.
