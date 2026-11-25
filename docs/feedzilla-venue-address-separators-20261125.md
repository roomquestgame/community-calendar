# Venue contact address separators

Knitting Factory renders `416 S. 9th St - Boise, ID 83702`. The contact parser
previously retained `- Boise` as the city, which failed the database's independent
geocoder response validation. Parse street/city/state separately and emit a comma
separator. Preserve hyphens inside city names such as Winston-Salem. Venue identity
matching, ambiguous-address handling and geocoder validation stay unchanged.

Validation: 20 venue resolver tests and four separator subtests passed. Existing
bad cached addresses are corrected through normal Admin venue review using the
publisher evidence; no direct database updates. Preserve concurrent Spektrix work.
