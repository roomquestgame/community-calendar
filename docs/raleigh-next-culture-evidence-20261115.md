# Page 158 Books: complete native calendar capture

Reviewed November 15, 2026. This adapter is part of the four-source Raleigh
continuation batch. It adds only Page 158 Books; other prospects below remain
research notes. Existing healthy sources and held sources were excluded using
the backend's November 15 registry inventory.

## Exact source and transport

| Field | Value |
| --- | --- |
| Source key | `page158_books_wake_forest_nc` |
| Registered calendar | `https://page158books.com/events/list/upcoming-events` |
| Kind / adapter | `html` / `html` |
| Time zone | `America/New_York` |
| Allowed request host | `page158books.com` |
| Listing requests | Exact calendar, then its published `?page=1` through `?page=5` links |
| Detail requests | Published `/event/YYYY-MM-DD/slug` links, one per native occurrence |
| Description limit | 12,000 characters; an oversized body is held, never truncated |
| Eligible manifest / event caps | 200 / 200 |
| Listing page cap | 20, with 25 cards per nonfinal page |
| Checkpoint cap | 850,000 bytes |
| Requests per chunk | At most three ordinary guarded GETs |

The official listing directly supplies every detail URL, dated native ID, title,
time text and address block. Its pager exposes the current, next and final page.
The adapter exhausts the complete published list before processing any detail,
checks the page count remains stable, and rejects duplicate native IDs or URLs,
page jumps and missing pagination evidence. It selects the exact 60 local days
from the capture's anchor date; it does not expand recurring patterns.

Research used the existing robots-aware capture helper and its unchanged
`RoomQuestCommunityCalendar/0.2 (+https://roomquestapp.vercel.app/)` identity.
Both robots checks returned HTTP 200 and allowed the requested paths. All 52
uncached listing/detail requests in the full-capture receipt returned HTTP 200;
five additional pages were already present in the helper's cache. The complete
snapshot contains six list pages and 51 detail pages. No redirects, cookies,
authentication, proxy changes or alternate access routes were used.

This proves ordinary access from the research environment. Production access
remains subject to the unchanged worker's robots, DNS, redirects, pacing, body
limits and HTTP failure handling. It does not assert publisher consent or alter
rights metadata.

## Frozen capture and replay

Capture ran from `2026-11-15T13:49:00.937315+00:00` to
`2026-11-15T13:54:51.232758+00:00`. The offline replay anchor is
`2026-11-15T13:00:00+00:00`; its local window is November 15 through January 13,
inclusive, ending at January 14 local midnight.

| Measure | Result |
| --- | ---: |
| Complete listing pages | 6 |
| Dated native entries across all pages | 131 |
| Entries outside the 60-day window | 80 |
| Eligible detail pages, all captured | 51 |
| Accepted occurrences | 37 |
| Held occurrences | 14 |
| Blank native description bodies | 13 |
| Explicit date conflicts | 1 |
| Native coordinate pairs | 0 |
| Duplicate normalized occurrences | 0 |
| Longest accepted full description | 2,213 characters |
| Final checkpoint | 100,602 bytes |
| Largest captured response | 119,075 bytes |
| Resumable chunks | 19 |

All thirteen blank bodies are the publisher's individual Storytime details;
listing teasers and descriptions from other occurrences are not substituted.
The Holiday Market detail has November 21 in its canonical dated URL, native
JSON-LD and visible schedule, while the event invitation explicitly says
November 7. That occurrence is held with `raleigh_culture_schedule_conflict`.
These are reviewable diagnostics, not unreported losses.

The January 3 Book Club Against Authoritarianism is explicitly scheduled at
3:45 a.m. in the listing, visible detail and native JSON-LD, which ends at
4:45 a.m. The narrative supplies no conflicting clock. The adapter preserves
that native time; it does not silently change a.m. to p.m.

Every accepted narrative was compared with the complete cleaned native detail
body at a 100,000-character verification limit. Every accepted address and
instant was compared with its own visible address and native start/end values.
All comparisons matched. Native category tags and same-host event image URLs
are retained as publisher metadata; no classifier labels are forced.

| Occurrences | Native venue | Preserved street address |
| ---: | --- | --- |
| 33 | Page 158 Books | `415 Brooks Street Suite B, Wake Forest, NC 27587-2930` |
| 4 | Norse Brewing, Lower Level | `203 Brooks St, Wake Forest, NC 27587` |

The publisher's JSON-LD locality redundantly includes the street and can omit
the suite. The visible native address block is complete and supplies the venue,
street, suite or room, city, state and ZIP. Listing and detail address blocks
must agree when both are complete. No default venue or coordinate is supplied.
All current rows use `publisher_event_address_pending_geocode` with paired null
coordinates. Explicit valid native event coordinates, if later supplied, have
a separate `publisher_event_geo` path and must be finite and inside NC.

Temporary evidence (full publisher bodies are not committed):

- `/tmp/raleigh-next-culture-captures/page158-full-capture.json`: URL, native ID,
  local path, body hash, response size and access receipt for all captured pages.
- `/tmp/page158_books_wake_forest_nc-next-replay.json`: complete normalized rows,
  checkpoint, per-chunk progress, diagnostic outcomes and validation summary.
- `/tmp/replay_page158_complete.py`: reproducible offline comparison using only
  the captured bodies, with no publisher requests.

## Durable completion contract

The shared Raleigh source wrapper registers this family as `next_culture_v1`.
Its usual version/source/hash/events/diagnostics/60-day window checks remain.
Additional state fields are `phase`, `listing_complete`, `next_page`,
`listed_pages`, `listing_total_pages`, `listing_seen`, `outside_window_count`,
`queue`, `outcomes` and `state_hash`. The source manifest hash covers the exact
eligible detail queue; the state hash covers all fields except itself.

A completed checkpoint requires all of the following:

- `phase == 'details'` and `listing_complete is True`.
- `next_page` is explicitly present and null.
- `listed_pages` is the exact ordered sequence of one to twenty published
  calendar pages and agrees with `listing_total_pages`.
- `cursor == manifest_count == len(queue) == len(outcomes)`.
- `len(events) + len(diagnostics) == cursor`: one event or one held outcome per
  dated detail, with no generated recurrence instances.
- `len(listing_seen) == manifest_count + outside_window_count`.
- Every accepted record and held diagnostic matches its persisted per-item
  proof; mutations cannot pass by recalculating only the outer state hash.

Partial chunks return an empty public `events` result while retaining accepted
rows inside the checkpoint. Only complete capture exposes the full snapshot to
staging. The current 19-chunk replay validated every intermediate checkpoint and
its accumulated rows with both the adapter and shared Raleigh validators.

The focused fixture suite has 26 passing checks, covering full prose retention,
blank/oversized body holds, native address variants, explicit native coordinates,
time-zone and visible/native schedule agreement, early-morning time retention,
date-conflict holds, cancelled/online records, invalid point rejection,
pagination integrity, complete-only exposure and checkpoint corruption. Fixtures
contain synthetic descriptions rather than copied publisher bodies. Routine
GitHub Actions checks are not dispatched under the owner's repository policy.

## Other culture prospects: research only

These candidates were not selected for this batch. No additional requests were
made after the root narrowed the culture task to Page 158.

| Prospect | Official evidence | Current finding |
| --- | --- | --- |
| Paper & Stars Studio | `https://www.paperandstarsstudio.com/rsvp`, linking to `https://www.eventbrite.com/o/paper-amp-stars-studio-21752275476` | Both accessible with robots approval. Native organizer data exposes one upcoming event, total one, and `hasMoreUpcoming=false`. Its exact linked detail `https://www.eventbrite.com/e/merry-bright-a-frozen-holiday-celebration-2026-tickets-1984295103069` has full visible prose, December 12 10 a.m.–2 p.m., Mordecai Historic Park, 1 Mimosa Street, Raleigh, NC 27604, and a native coordinate pair. Future viable prospect; not implemented. |
| So & So Books | `https://www.soandsobooks.com/` | Homepage accessible with robots approval. The captured Square Online shell exposes shopping content and social links; a complete dated event feed was not established. |
| Liberation Station | `https://liberationstationbookstore.com/events/` | Accessible native event page was empty. Its directly linked `/new-events/calendar/` returned 301; the guarded helper stopped without following another route. Complete upcoming feed unverified. |
| Gamers Armory | `https://gamersarmory.com/events/` | Accessible official page contains an undated weekly list, which is insufficient for occurrence generation. Its linked `https://www.meetup.com/the-gamers-armory/events/calendar/` passed robots but the page timed out; no retry or alternate feed was attempted. |
| AR Workshop Raleigh / Cary | Official location links `https://www.arworkshop.com/raleigh` and `https://www.arworkshop.com/cary/` | Web retrieval resolved to the general location directory, whose current list omitted these locations. No current complete native calendar was established; no closure assertion or adapter was made. |
| Dog-Eared Books | `https://dogearedbooksnc.squarespace.com/` | Official search results found; publisher calendar capture was not started before the batch scope was frozen. |

Quail Ridge Books and Blackbird Books retain their existing production HTTP 403
holds and were not contacted. NC Museum of Art, Raleigh City Farm, MAKRS,
Triangle Pop-Up and Volumes & Vices already have healthy sources and were not
duplicated. Lack of a dedicated registration for a prospect is not proof of zero
cross-provider event overlap.
