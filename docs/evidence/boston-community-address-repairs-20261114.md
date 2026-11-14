# Boston community: exact remaining address holds

These follow-up changes apply only to still-unpublished B1 occurrences at four
exact source, native venue and full-street tuples. They add verified public-site
coordinates and provenance. **Full native descriptions, street strings, venue
names, event dates and identities remain unchanged.**

| Source / native venue | Retained native street | Reviewed latitude, longitude | Evidence |
|---|---|---|---|
| Boston Food Forest Coalition / Uphams Corner Food Forest | 11 A Everett Avenue, Boston, MA 02125 | 42.315585, -71.063221 | Official forest directory links the target for 11A Everett Avenue, Dorchester 02125. |
| Boston Food Forest Coalition / Hope Garden | 424 Geneva Avenue, Boston, MA 02122 | 42.3007808, -71.0667882 | Official Hope Garden link targets the 424–428A Geneva Avenue parcel containing the native event's 424 address. |
| Friends of Titus Sparrow Park / Museum of Fine Arts, Boston (MFA) | 465 Huntington Avenue, Boston, MA 02115 | 42.339381, -71.094048 | Museum partner profile's `Museum.geo` explicitly binds this street and ZIP; the official MassGIS/MHC building independently corroborates the site. |
| City of Boston / Union Church | 485 Columbus Avenue, South End, MA 02118 | 42.3431615, -71.0791651 | Church's native Wix `businessLocationCoordinates`, street number/name and postal code agree. Its official Boston city spelling corroborates the unchanged South End neighborhood spelling. |

The forest points come from the links' `!3d`/`!4d` **target markers**, not their
separate `@` map viewport centers. The MFA partner point likewise comes from an
explicit Museum/GeoCoordinates object and matching marker. MassGIS inventory
record **BOS.7493 / OBJECTID 47251** names the Boston Museum of Fine Arts at
465 Huntington Avenue; the separate same-address statue record is excluded.
The MassGIS building point is approximately 11 meters from the partner marker,
corroborating the same museum site. The arts collector and Titus event use the
same reviewed partner point.

Matching remains narrow. A different source, venue spelling, annex, street
number or ZIP does not inherit these points. Focused positive and near-miss
tests cover all four corrections. Full captured replay verifies that only the
point, missing-geo reason and location provenance change; native prose and
street equality remain exact. The machine-readable companion includes hashes,
affected event identities and the resulting points. The initial baseline
capture is retained separately from the corrected replay output.

## Evidence

- [Boston Food Forest Coalition official locations](https://www.bostonfoodforest.org/locations)
- [Upham's Corner food forest](https://www.bostonfoodforest.org/uphams-corner-food-forest)
- [Hope Garden](https://www.bostonfoodforest.org/hero-hope-garden)
- [Union Church visit page](https://www.unionboston.org/visit)
- [Museum of Fine Arts partner profile](https://artsandculture.google.com/partner/museum-of-fine-arts-boston)
- [Official MFA directions and postal address](https://www.mfa.org/visit/getting-here)
- [MassGIS/MHC inventory dataset](https://services1.arcgis.com/hGdibHYSPO59RG1h/ArcGIS/rest/services/MHC_Inventory_GDB/FeatureServer/0)

No production success is claimed by the local replay. The batched deployment
receipt must verify that these previously held occurrences publish with the
unchanged native streets and newly verified points.
