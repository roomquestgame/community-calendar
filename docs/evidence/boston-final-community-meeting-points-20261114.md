# Final Boston community meeting-point corrections

The frozen final delta covers **11 exact venue tuples, 17 occurrences and four sources**. It changes coordinates and location evidence/provenance while preserving every native description, street, title, event identity and schedule. Completed production passes identified these as the remaining unpublished locations. Venues that resolved normally are excluded.

| Source | Preserved venue and street | Reviewed point | Occurrences |
|---|---|---|---:|
| Boston Cares (5623) | ABCD Geneva; 198 Geneva Avenue, Dorchester, MA 02121 | 42.305581, -71.075595 | 2 |
| Boston Cares (5623) | Charles Street AME Church market; 13 Elm Hill Avenue, Dorchester, MA 02121 | 42.312876, -71.084335 | 1 |
| Boston Cares (5623) | Charlestown BHA market; 38 O'Reilly Way, Charlestown, MA 02129 | 42.377886, -71.058355 | 1 |
| Boston Cares (5623) | Friday Night Supper Program at Arlington Street Church; 351 Boylston Street, Boston, MA 02116 | 42.35203, -71.071219 | 3 |
| Boston Cares (5623) | Lenox Camden market; 32 Kendall Street, Boston, MA 02118 | 42.335881, -71.082262 | 1 |
| Boston Cares (5623) | Mario Umana Academy market; 312 Border Street, East Boston, MA 02128 | 42.378386, -71.040458 | 1 |
| Boston Cares (5623) | United Housing market; 3 Quincy Street, Dorchester, MA 02121 | 42.31617, -71.08221 | 1 |
| Nature Center (5625) | Millennium Park parking lot near canoe launch; 300 Gardner Street, West Roxbury, MA 02132 | 42.280515, -71.184852 | 1 |
| Nature Center (5625) | Sullivan's Castle Island parking lot; 2080 William J Day Boulevard, South Boston, MA 02127 | 42.338845, -71.013235 | 1 |
| Boston College (4318) | Trinity Chapel; 883 Centre Street, Newton, MA 02459 | 42.342777, -71.19355 | 3 |
| Greenway (5630) | Armenian Heritage Park; 115 Atlantic Avenue, Boston, MA 02110 | 42.36092235, -71.0532390073 | 2 |

## Primary point evidence

[Boston College’s Trinity Chapel place](https://events.bc.edu/trinity_chapel), verified Localist ID 190153, supplies the named chapel point and the 883 Centre Street display address. Its internal geocode street uses the campus’s 885 Centre Street alias with the same Newton ZIP. The correction binds the point to the exact chapel label and retained display street.

Sullivan’s uses Boston SAM address 149843 / building 157039 at 2080 William J Day Boulevard, corroborated by the [restaurant location](https://www.sullivanscastleisland.com/location/castle-island/) and [current meeting directions](https://www.massaudubon.org/programs/boston-nature-center/104044-arctic-waterbirds-at-castle-island) that gather in front of the restaurant. Millennium Park uses the co-organizer’s current [named canoe-launch Place.geo](https://www.brooklinebirdclub.org/tripevent/millennium-park-5/), repeated on its [March 2027 event](https://www.brooklinebirdclub.org/tripevent/millennium-park-8/) and matching the [current Nature program’s directions](https://www.massaudubon.org/programs/boston-nature-center/104051-ducks-herons-more-at-millennium-park).

ABCD Geneva uses exact SAM address 165585 / building 182767 at 198 Geneva Avenue, confirmed by [ABCD](https://bostonabcd.org/location/abcd-dorchester-head-start/). The parcel’s separate primary frontage at 188 Geneva is recorded without replacing the native 198 street. Friday Night Supper uses exact SAM address 352350 / building 138413 at 351 Boylston, confirmed by the [program](https://www.fridaynightsupper.org/contact/). Mario Umana uses exact SAM address 155833 / building 129848 at 312 Border Street and the current [Fresh Truck schedule](https://cdn.shopify.com/s/files/1/0582/7896/9428/files/November_26.pdf?v=1793643796). These points identify address sites; precise doors or truck curb positions are not asserted.

Armenian Heritage Park uses the [Greenway’s official interactive map](https://www.rosekennedygreenway.org/map/), script `oum-init-map`, named park marker 27465 with `geometry_type=point`. The separate sculpture marker and viewport are excluded. [Park directions](https://www.armenianheritagepark.org/directions-parking) confirm 115 Atlantic Avenue.

## Explicit local-context inferences

The user authorized educated local resolution where exact data is unavailable. These four points preserve the operator’s current street and record their precision in row provenance.

- **Lenox Camden:** official SAM address 166706 / building 240453 gives the 30–40 Kendall Street range containing native number 32. The current [operator calendar](https://ft-calendar.vercel.app/truck) and schedule confirm 32 Kendall Street, Boston, MA 02118. SAM’s 02120 / Mission Hill label conflicts with that postal text; the disagreement remains explicit while 02118 is retained. The independent city locator’s 32 Kendall result references the same range and corroborates the site within 0.25 metres.
- **Charles Street AME market:** current operator directions place the truck in the church lot off Elm Hill. The [church FAQ](https://www.csamechurch.org/faq) corroborates its parking site at 5 Elm Hill; the operator’s 13 Elm Hill street is preserved. The approved point is the area-weighted centroid inside contiguous municipal parcels 1202101000 and 1202102000, approximately 26 metres from their farthest boundary.
- **Charlestown BHA:** current operator directions specify private street parking at 38 O’Reilly Way. Official SAM segment 10894 / OBJECTID 12553 has right-even numbers 48 through 30. Arc-length interpolation at a fraction of 10/18 estimates number 38’s street position, with no speculative curb offset.
- **United Housing:** current directions place the stop on Quincy Street from Warren, on the right past the Neighborhood Network Center lot. Official Quincy Street segment 25632 and NNC parcel 1202832000 support a site estimate five metres east beyond the lot’s projected frontage, rounded to five decimals. The native 3 Quincy Street, Dorchester, MA 02121 remains unchanged. Wrong Quincy Place/Court candidates, pure house-number interpolation before the named lot and headquarters substitutions were rejected.

These estimates do not claim exact numbered doors or truck positions. The JSON includes the primary street and parcel records, current operator directions, inference methods, source URLs, raw-capture paths and SHA-256 hashes. The church centroid and Charlestown interpolation were independently recomputed and match the approved rounded points.

## Verification and release boundary

**181 focused tests pass.** They preserve full native prose and event identity, enforce exact source/venue/street matches, retain inference notes outside the description, and reject poisoned Nature/Greenway checkpoint coordinates, venue, street, evidence, provenance or point presence even after rehashing. Legacy no-point prefixes remain resumable. The existing deadline reserve, continuation cap and hard checkpoint limits remain in place.

The complete **300-row captured replay** differs from frozen B3 on exactly **17 rows**, solely in coordinates and location reason/evidence/provenance. Every native body, street, title, ID, start and end compares exactly. Actual-worker replay with mocked transport and RPCs stages only complete snapshots: Boston College has 76 records in one claim, Greenway 70 in nine claims, Nature 21 in four claims, and Cares 133 in one claim. Replay performs no live writes.

The arts agent independently compared the B3 module and capture against this final delta, confirming the 11 tuples, 17 changed occurrences, unchanged native event facts and bounded checkpoint validation without finding a blocker.

Menino YMCA, Village at Brookline, Villa Victoria, St. Luke’s, HI Boston and Mission Park resolved through ordinary processing and are excluded from this final point delta. The release is consolidated across all four sources. Actual deployment and final public description/street equality are recorded in the separate production receipt.
