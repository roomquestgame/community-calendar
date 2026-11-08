# Pint Nine: retain secondary address evidence

Pint Nine's official calendar was collected successfully, but its eight staged
events could not publish because its suite address remained ambiguous. Kros
Strain and Hurrdat showed the same first-attempt failure.

`result_address_parts` kept the house number and street while discarding the
provider's `unit_type` and `unit_number`. The requested address retained its
suite, so even a correct structured suite response could not pass the exact
street comparison. Geocodio documents these secondary components in its
[API reference](https://www.geocod.io/docs/).

The fix appends those two fields to the existing street reconstruction. It
changes no normalization aliases, query/cache keys, confidence, precision,
country, locality, ZIP, ambiguity, authorization, reservation, quota, pacing or
retry policy. Missing or mismatched provider units remain rejected. No
coordinates are supplied by this change.

Focused regression cases use the three observed query shapes with synthetic
provider evidence. They exercise the real provider-response verification path,
missing/wrong units, optional empty fields, confidence, country/state/number and
second-candidate rejection. All transport is mocked; no provider request or
database write is performed by those tests.

The paired backend change is
[RoomQuestGame PR #690](https://github.com/roomquestgame/RoomQuestGame/pull/690).
Deploy and verify this collector commit before applying backend migration
`20261108031602_geocoder_secondary_address_verification.sql`. That migration
retains unit components in the independent database verifier and reopens only
the three exact observed first-attempt failures. Normal demand, new quota
reservations and fresh verified provider evidence remain required.

At preparation, this collector release and the actual production retry remain
pending. Record ready-head CI, deployment and live acceptance receipts in the
associated PR. The original rejected live provider response was not retained,
so this reproducible defect alone does not prove the retry will satisfy every
other address check. No mobile release or broad refresh-error fix is included.
