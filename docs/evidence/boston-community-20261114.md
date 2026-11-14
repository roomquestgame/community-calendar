# Boston community, outdoors and fitness intake — November 14, 2026

## Scope and implementation

The review excludes the already live MIT, MassArt, Northeastern, Freedom Trail,
Brookline Bird Club and Community Music Center sources. It adds six new
publishers and repairs the existing empty Boston Cyclists Union source while
preserving its source key, ID and event IDs. Root-owned registration converts
that source from its old JSON/WordPress route to the scoped HTML collector.

`roomquest/boston_community.py` reuses `mapsee_adapter.record`, the shared full
description sanitizer and the existing Squarespace Google-calendar timestamp
parser. Its five Squarespace calendars fetch permitted listing/detail HTML,
not JSON or ICS export URLs. They use the existing durable snapshot contract;
unfinished or failed detail passes emit no partial event snapshot. The City of
Boston uses one official RSS document; Cyclists uses bounded TEC REST pagination.

## Local snapshot replay

These counts describe the captured official publisher content at review time,
not an assertion that ingestion or production deployment has succeeded.

| Publisher | Official calendar | Eligible timed physical events | Full descriptions | Full streets | Native Boston points |
| --- | --- | ---: | ---: | ---: | ---: |
| Boston Food Forest Coalition | https://www.bostonfoodforest.org/workshops | 5 | 5 | 5 | 3 |
| Backyard Boston | https://www.backyardbos.com/upcoming-events | 3 | 3 | 3 | 3 |
| Friends of Titus Sparrow Park | https://www.titussparrowpark.org/events | 4 | 4 | 4 | 0 |
| Charles River Watershed Association | https://www.crwa.org/events | 1 | 1 | 1 | 1 |
| New England Gator Club | https://newenglandgatorclub.org/events | 4 | 4 | 4 | 4 |
| City of Boston Events | https://www.boston.gov/rss/events | 4 | 4 | 4 | 0 |
| Boston Cyclists Union (existing-source repair) | https://bostoncyclistsunion.org/events/ | 1 | 1 | 1 | 0 |
| **Total** | | **22** | **22** | **22** | **11** |

Full native descriptions range from 150 to 1,969 characters. The 150-character
Old West Church narrative is the complete published body; it is not a clipped
summary. Regression coverage verifies preservation of descriptions over 2,000
characters and refusal rather than clipping above the 12,000-character limit.
There are no synthesized description fallbacks. Existing publisher image URLs
are carried only from the event's full body or own metadata.

The JSON companion lists exact source keys, feed URLs, description lengths and
street addresses. Public HTML/XML snapshots and parsed rows remain in scratch
for local review, not in this repository.

## Source data corrections and held records

1. **Coordinates:** Food Forest and Titus Sparrow emit generic Manhattan
   coordinates for some Boston events. The collector requires agreement of the
   event's visible address, calendar-export location and map destination before
   accepting its own event OG coordinates, and applies Boston-area bounds.
   Defaults/contradictions become `null` coordinates with the full street retained
   for the ordinary geocoder. They never become Boston event pins in New York.
2. **City clocks:** Boston.gov RSS labels displayed Eastern wall times with `Z`.
   For example, its 10 AM Mattapan clinic is explicitly displayed as 10 AM on the
   publisher. Every corrected timestamp must agree with the visible local day,
   hour and minute. RSS `pubDate` is never used as an event time. Missing end
   times remain missing. Duplicate copies of the same occurrence collapse.
3. **City addresses:** The City feed omits state/ZIP on two reviewed venue
   records. The collector supplies Massachusetts for this municipal feed and
   fills ZIP only for exact name/street/locality tuples: Mattapan BPL,
   1350 Blue Hill Ave, Mattapan MA 02126; and Union Church,
   485 Columbus Avenue, South End MA 02118. The BPL branch reference is
   https://www.bpl.org/locations/mattapan/; Titus Sparrow's own volunteer event confirms
   Union Church at the same numbered street and ZIP. Other incomplete unknown
   addresses are held rather than assigned a headquarters address.
4. **Leland work-party duration:** The November 21 event header ends at 11:30 AM;
   the full narrative says 10:30 AM–4 PM. This record is explicitly held for
   `boston_community_schedule_conflict` until the publisher metadata agrees.
5. **Other held current records:** Food Forest's Giving Tuesday has no physical
   venue; CRWA's December community meeting is virtual; the City RSS contains
   virtual/unlocated records. None receives an invented street or location.
6. **Eligibility:** Backyard's December 31 Throwdown is described as members-only
   with an invitation to join and register. The complete eligibility text is
   retained. It is not misrepresented as a free unrestricted public workout.

## Additional discovery and unresolved sources

| Candidate | Evidence / remaining work |
| --- | --- |
| JP Centre Yoga | Official https://www.jpcentreyoga.com/events and robots path returned a `Site Unavailable` response. A public Squarespace alias exposed 42 upcoming records during discovery, but no alias or challenge workaround is integrated. Official contact/FAQ identifies 670 Centre Street, Jamaica Plain MA 02130. Hold until ordinary publisher transport works. |
| Rose Kennedy Greenway | https://www.rosekennedygreenway.org/calendar/ shows active fitness, volunteer, market and family programs. Its `/events.ics` and Events Manager ICS export return HTTP 500 and incomplete calendars. A separate Events Manager HTML integration remains. |
| Esplanade Association | https://esplanade.org/events/ publishes eight public Google calendar IDs. Seven had no future occurrences; the main calendar had a November 17 cleanup with a plus-code meeting location. A verified full street meeting point is still needed. |
| Boston Nature Center | https://www.massaudubon.org/programs/boston-nature-center has active November/December family and birding programs. Listing/detail HTML needs a dedicated parser; do not substitute schema metadata from unrelated pages. |
| Boston Cares | https://www.bostoncares.org/calendar is an active public volunteer calendar with dynamically loaded opportunity data. An anonymous public calendar integration still needs review. |
| Boston College | https://events.bc.edu/api/2/events is functioning Localist with full descriptions, event instances, streets and geographic metadata. Root must complete separate registry/production comparison before adding or repairing. |
| Waterfront Coalition | https://www.bostonwaterfrontcoalition.org/events has five upcoming Squarespace items, mainly ICA programs also available from the institution directly. Avoid duplicate collector registration without remaining-item review. |
| Union Park Neighborhood Association | https://www.upna.org/events has a future holiday event with venue `TBD`; hold until the organizer supplies a real destination. |
| The Outside Social Club | https://www.weoutside.social/events had no upcoming events at review time. |
| Queer Neighborhood Council | https://www.tqnc.org/events has a useful upcoming calendar, but four of five items have no meaningful native text beyond image/link content. Do not fabricate descriptions. |
| Community Alliance of Mission Hill | https://www.camh.boston/events has two text-described meetings and other image-only or blank-description programs. Mixed quality needs per-event coverage before intake. |
| East Boston Social Centers | https://www.ebsocialcenters.org/events had only image/link text for current items; full descriptions require publisher-detail review. |
| 22Mohawks | https://www.22mohawks.com/events has future veteran/volunteer programs with full bodies but no structured locations and generic default coordinates. Venue extraction from individual descriptions remains. |

## Validation and deployment boundary

- Sixteen local regression cases pass, including long descriptions, over-limit
  rejection, empty text, default NYC pins, virtual locations, interrupted
  multi-chunk collection, poisoned checkpoints, changed detail identity,
  contradictory schedules, RSS clock correction, duplicate occurrences,
  missing end times and preserved Cyclists event IDs.
- Ordinary `fetch_publisher(..., respect_robots=True)` was attempted against all
  source hosts. This execution environment returns `dns_unavailable` before
  requesting the publisher. The collector contains no DNS bypass, robots
  exception, special challenge handling or alternate-host fallback.
- Live guarded production/Actions fetch, geocoding of the eleven records
  without trustworthy native points, complete-description database gates,
  staging, and public-row verification remain root-owned deployment gates.
- No routine GitHub provider-test workflow was dispatched. No commit, merge or
  production mutation was made by this subtask.
