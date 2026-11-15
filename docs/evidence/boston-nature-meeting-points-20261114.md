# Boston Nature Center: two remaining meeting points

The completed production snapshot published 19 of 21 Boston Nature Center occurrences. Two included bird walks remained in the address queue. This local follow-up attaches reviewed coordinates to their exact source, native venue label, and full street; their descriptions, dates, titles, identities, and addresses remain unchanged. It preserves the already deployed B3 source and continuation changes.

| Native event | Preserved meeting site | Reviewed latitude, longitude | Primary evidence |
| --- | --- | --- | --- |
| Arctic Waterbirds at Castle Island; `nature:104044:2026-11-22T13:00:00+00:00` | Sullivan's Castle Island parking lot; 2080 William J Day Boulevard, South Boston, MA 02127 | 42.338845, -71.013235 | Boston SAM primary address 149843 / building 157039 supplies exact street, neighborhood, ZIP, and geometry. [Sullivan's official location](https://www.sullivanscastleisland.com/location/castle-island/) corroborates the restaurant. [Current program instructions](https://www.massaudubon.org/programs/boston-nature-center/104044-arctic-waterbirds-at-castle-island) place the group in front of that restaurant, next to its parking lot. The point represents this named restaurant site. |
| Ducks, Herons, & More at Millennium Park; `nature:104051:2026-12-13T13:00:00+00:00` | Millennium Park parking lot near canoe launch; 300 Gardner Street, West Roxbury, MA 02132 | 42.280515, -71.184852 | The program co-organizer's [current November 2026 page](https://www.brooklinebirdclub.org/tripevent/millennium-park-5/) supplies explicit `Place.geo` for the named Millennium Park Canoe Launch and this street/ZIP. Its [March 2027 page](https://www.brooklinebirdclub.org/tripevent/millennium-park-8/) repeats the point. [Current Mass Audubon directions](https://www.massaudubon.org/programs/boston-nature-center/104051-ducks-herons-more-at-millennium-park) specify the parking lot nearest that launch. |

The Millennium coordinates come from the current named venue metadata, not a park-wide map center. An earlier search-cache result for a 2024 event gave a point about 11 meters away; its live URL now returns 404, so it is retained only as a superseded discovery clue. The current primary pages returned 200 and match the stated meeting site.

## Checkpoint and data verification

The source is collected through durable checkpoints. The validator now permits these two points only when the source key, native venue label, full street, both coordinates, evidence URL, and provenance match the reviewed tuple. Tests change each field, recompute the outer row hash, and confirm the independently pinned location still rejects the poisoned checkpoint. Dropping a newly reviewed point also fails. Existing checkpoints containing an older no-point prefix remain resumable.

The focused suite passed **136 tests**. The full captured replay retains **300 records** across all four remaining-source collectors, with exactly **two** changed records. Only coordinates, location reason, evidence, and provenance differ from the B3 frozen capture. Every complete native description, street, title, date, and identity compares exactly. The new Nature checkpoint is 56,079 bytes, below the unchanged 900,000-byte bound.

The same captures pass through the actual worker with transport and RPC mocks: Boston College stages 76 records, Greenway 70, Nature Center 21, and Boston Cares 133. Nature Center still completes in four captured claims, with no staging before the checkpoint is complete. The B3 eight-detail admission cap and 18-second reserve remain unchanged.

## Scope and status

The accompanying JSON receipt retains authoritative records, raw-capture hashes, exact changed identities, and full-description hashes. Evidence HTTP reads honored the public robots policies. A local `fetch_publisher` probe reported unavailable DNS; no production transport change or access-denial bypass is proposed.

No production mutation or deployment is performed by this local review. The two corrections are prepared for the final consolidated remaining-items release; publication status is recorded separately in the production receipt.
