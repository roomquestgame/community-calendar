# Boston source expansion — November 14, 2026

## Reviewed first release batch

This ledger contains only newly discovered feeds and one registered source with no active public occurrences. It is a prepared release inventory; source captures are not production results. Existing working production coverage is excluded.

All sources enter the existing HTML category worker with exact feed identity, America/New_York clocks, ordinary guarded publisher requests, full narrative validation, and complete street addresses. The matching application migration is `20261114230726_boston_source_expansion.sql`. Twenty-one calendars reuse the durable complete-only checkpoint path. No partial detail snapshot is staged.

| Publisher | Official calendar | Change | Captured occurrences | Window / method |
| --- | --- | --- | ---: | --- |
| Aeronaut Brewing Company | [https://www.aeronautbrewing.com/visit/somerville/](https://www.aeronautbrewing.com/visit/somerville/) | New source | 61 | Explicit timed native occurrences in the next 60 days; ongoing programs retained when their verified end is future. |
| Arts at the Armory | [https://artsatthearmory.org/events.ics](https://artsatthearmory.org/events.ics) | New source | 55 | Native ICS descriptions; reviewed Cafe/Performance Hall categories identify onsite rooms at 191 Highland Avenue. |
| Backyard Boston | [https://www.backyardbos.com/upcoming-events](https://www.backyardbos.com/upcoming-events) | New source | 3 | Official community fitness, fundraising and competition calendar; 5 Necco Street. |
| The Bebop | [https://www.thebebopboston.com/new-events](https://www.thebebopboston.com/new-events) | New source | 21 | Explicit timed native occurrences in the next 60 days; ongoing programs retained when their verified end is future. |
| Boston Food Forest Coalition | [https://www.bostonfoodforest.org/workshops](https://www.bostonfoodforest.org/workshops) | New source | 5 | Official dated garden stewardship and workshops; full event HTML and per-event streets. |
| Boston Public Library | [https://bpl.bibliocommons.com/v2/events](https://bpl.bibliocommons.com/v2/events) | New source | 306 | Complete rolling 7-day window of physical branch/offsite events; native gateway date filters are ignored upstream. |
| Boston Public Market | [https://bostonpublicmarket.org/events/](https://bostonpublicmarket.org/events/) | New source | 39 | Explicit timed native occurrences in the next 60 days; ongoing programs retained when their verified end is future. |
| Brookline Booksmith | [https://brooklinebooksmith.com/upcoming-events](https://brooklinebooksmith.com/upcoming-events) | New source | 20 | Explicit timed native occurrences in the next 60 days; ongoing programs retained when their verified end is future. |
| Castle Island Brewing | [https://www.castleislandbeer.com/calendar](https://www.castleislandbeer.com/calendar) | New source | 11 | Explicit timed native occurrences in the next 60 days; ongoing programs retained when their verified end is future. |
| Charles River Watershed Association | [https://www.crwa.org/events](https://www.crwa.org/events) | New source | 1 | Official river ecology and community programs; virtual-only events held out of physical map results. |
| City of Boston Events | [https://www.boston.gov/rss/events](https://www.boston.gov/rss/events) | New source | 4 | Official RSS, all 25 published items consumed; event times come from visible Eastern clocks, never pubDate. |
| Club Café Boston | [https://www.clubcafe.com/club-events/](https://www.clubcafe.com/club-events/) | New source | 12 | Explicit timed native occurrences in the next 60 days; ongoing programs retained when their verified end is future. |
| Dorchester Brewing Company | [https://www.dorchesterbrewing.com/events/](https://www.dorchesterbrewing.com/events/) | New source | 6 | Explicit timed native occurrences in the next 60 days; ongoing programs retained when their verified end is future. |
| Harvard Book Store | [https://www.harvard.com/upcoming-events](https://www.harvard.com/upcoming-events) | New source | 22 | Explicit timed native occurrences in the next 60 days; ongoing programs retained when their verified end is future. |
| Lamplighter Brewing Company | [https://lamplighterbrewing.com/collections/events](https://lamplighterbrewing.com/collections/events) | New source | 13 | Explicit timed native occurrences in the next 60 days; ongoing programs retained when their verified end is future. |
| Mill Forge Makerspace | [https://millforge.org/events/](https://millforge.org/events/) | New source | 9 | Explicit timed native occurrences in the next 60 days; ongoing programs retained when their verified end is future. |
| Boston Cyclists Union | [https://bostoncyclistsunion.org](https://bostoncyclistsunion.org) | Repair existing empty feed | 1 | Existing empty source repaired through its official TEC REST feed; identity and native event IDs retained. |
| New England Gator Club | [https://newenglandgatorclub.org/events](https://newenglandgatorclub.org/events) | New source | 4 | Official Boston watch parties and volunteer events; tentative/unlocated travel held. |
| Notch Brewing Brighton | [https://www.notchbrewing.com/brighton-events](https://www.notchbrewing.com/brighton-events) | New source | 6 | Explicit timed native occurrences in the next 60 days; ongoing programs retained when their verified end is future. |
| Pandemonium Books & Games | [https://pandemoniumbooks.com/apps/bookthatapp/calendar](https://pandemoniumbooks.com/apps/bookthatapp/calendar) | New source | 168 | Explicit timed native occurrences in the next 60 days; ongoing programs retained when their verified end is future. |
| Pao Arts Center | [https://www.paoartscenter.org/events](https://www.paoartscenter.org/events) | New source | 4 | Permitted public HTML and full detail bodies; no robots-disallowed Squarespace JSON or ICS export. |
| Porter Square Books | [https://portersquarebooks.com/events](https://portersquarebooks.com/events) | New source | 18 | Explicit timed native occurrences in the next 60 days; ongoing programs retained when their verified end is future. |
| Remnant Brewing & Satellite | [https://www.remnantsomerville.com/live](https://www.remnantsomerville.com/live) | New source | 14 | Explicit timed native occurrences in the next 60 days; ongoing programs retained when their verified end is future. |
| SoWa Boston | [https://www.sowaboston.com/events/](https://www.sowaboston.com/events/) | New source | 1 | TEC First Friday calendar; Christmas Market lives on a separate seasonal page and is not inferred into this feed. |
| Friends of Titus Sparrow Park | [https://www.titussparrowpark.org/events](https://www.titussparrowpark.org/events) | New source | 4 | Official park, garden club and food-pantry programs; preserve each event's actual venue. |
| Trident Booksellers & Cafe | [https://tridentbookscafe.com/events](https://tridentbookscafe.com/events) | New source | Capture finishing | Explicit timed native occurrences in the next 60 days; ongoing programs retained when their verified end is future. |

## Remaining review and implementation

The next consolidated batch will review the accessible calendars below. None is represented as already deployed by this inventory.

- Registered zero-public repairs: Public Library of Brookline and ShowUp; Boston College is paused after a prior network failure and requires a complete identity/content review.
- Arts and family candidates: Museum of Fine Arts, ICA Boston, USS Constitution Museum, Boston Center for the Arts, and the separate SoWa Christmas Market program.
- Outdoors and community candidates: Rose Kennedy Greenway, Boston Nature Center, Boston Cares, and event-level meeting-point review for the Esplanade Association.

## Genuine access or publisher-content holds

- Google export routes for Tavern of Tales and Alpha Omega require robots permission; no denied endpoint is integrated.
- Roundhead presents a challenge response. JP Centre Yoga returns Site Unavailable on its official host. Boston Children’s Museum returns HTTP 403 during this review.
- Event-level missing descriptions, venue withheld until registration, virtual-only meetings, cancelled events and contradictory native start/end facts are explicitly excluded. The adapters never substitute titles for narratives or business headquarters for unknown event destinations.

## Evidence

- [Community and outdoors review](../../docs/evidence/boston-community-20261114.md)
- Arts and nightlife companion evidence is added with this release after complete capture validation.
- Final release receipts must identify the collector production commit, application merge, normal Database deploy run, source health, geocoding completion, and capture-to-staging-to-publication description/address equality.
