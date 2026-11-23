# Forestry venue name arrays

Live website acceptance showed Westonbirt's venue as a literal Python list
containing 'Westonbirt' and 'The National Arboretum' on all 32 published
occurrences. The publisher's captured JSON-LD supplies those two ordered text
components. The Forestry parser had passed that array to the generic text
formatter.

The scoped parser now joins valid nonempty text components as
'Westonbirt, The National Arboretum'. Empty or mixed-type name arrays fail the
existing venue-facts check instead of becoming display text. Scalar names keep
their existing handling.

The focused fixture test compares the complete parsed occurrence records from
the actual captured array with an equivalent single-string venue name. Event
identity, dates, full descriptions, evidence, addresses, and coordinates remain
identical. The full Forestry fixture file also verifies all 66 calendar scopes
and all 32 Westonbirt occurrences. No publisher fetch or database write is needed
for these checks.

Focused validation: python -m pytest -q tests/test_forestry_england.py passed
all 98 tests in 3.29 seconds on base 054e161. This includes the four new array
normalization/invalid-array cases and the all-network replay already in that file.

Existing public rows will be refreshed through the normal signed-in Admin
Check source flow after the collector release. This patch performs no operational
rewrite, registration, or deployment.
