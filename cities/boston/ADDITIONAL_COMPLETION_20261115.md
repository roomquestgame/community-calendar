# Additional Boston publication completion — November 15, 2026 UTC

The 21-profile enrollment was deployed after collector PR #229. Actual production
collection exposed four fixable gaps, consolidated in this completion batch.
Existing working/public profiles are outside the changes.

| Source | Observed problem | Reviewed correction | Captured occurrences |
| --- | --- | --- | ---: |
| The Burren | A new native showcase enumerates four comma-separated showtimes; another listing has a blank teaser but a complete linked narrative | Parse each explicit clock strictly and hydrate the linked full detail before deciding its description is absent | 123 |
| Long Live Roxbury | Exact street geocoder result is ambiguous | Publisher-linked verified venue supplies 42.3278,-71.0748 for 152 Hampden Street | 3 |
| Central Rock Cambridge | Exact street geocoder result is ambiguous | Official venue directions point 42.390776,-71.142459 at 170 Alewife Brook Parkway | 2 |
| Rock Spot South Boston | Exact street geocoder result is ambiguous | Official facility marker 42.3372967,-71.0561203 at 30 Old Colony Avenue; separate parking marker excluded | 136 |

All three points are bound to the exact source, venue name and full street. They
do not replace a native event point or apply to another site. Native descriptions,
addresses, titles, session clocks and identities remain intact. No generic
geocoder cache is modified.

## Verification

The Burren's 105 original captured rows remain identical. Its refreshed native
calendar adds 18 explicit occurrences, including the fully hydrated 960-character
Double Barrell/Mill Street description. All 123 records passed actual category-worker
replay; incomplete claims staged and published nothing. Long Live's three rows
change only geometry metadata and the resolved missing-geometry condition.
Eleven focused nightlife checks and eight focused community point checks pass.
An independent reviewer approved the parser, exact bindings and conditional
backend source refresh. Full narrative exports remain outside the repository;
the evidence records native IDs, hashes, clocks and provenance.

## Remaining transport and verification conditions

Arnold Arboretum remains paused after an actual production publisher HTTP 403.
No alternate access path or forced retry is introduced. Lizard Lounge exhausted its ordinary HTTP 504 retries and is now paused on an
external transport hold; no parser defect is established and no forced retry is introduced.
Coolidge and Eliot retain normal complete-only checkpoints and publisher pacing.

Seven apparent Tracksmith capture differences were traced to research capture
character decoding. Reconstructing the original UTF-8 bytes and running the
unchanged parser matches all 10 live staged records, including the explicit
December 14 yoga end. Production did not lose prose. The original capture is
preserved alongside the separately documented corrected comparison baseline.

## Release order

Deploy the merged collector first. The matching backend migration conditionally
resumes only Burren's exact reviewed parser-error state and refreshes the three
exact still-unpublished point targets. It preserves public events, manual reviews,
publisher access holds, retries and queue/lease limits, and wakes the normal HTML
batch once. Verify actual collection/publication after the guarded database run.
