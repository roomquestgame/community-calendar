# Reviewed UK venue addresses — EVE-150

The forward geocoder previously sent every request with `country=USA`, required
a US state, and stripped letters from provider postcodes. An exact Cambridge
venue address could not safely use that path. This change adds country-bound
UK handling for addresses explicitly reviewed in Admin, while preserving the
existing US matching and provider precision policy.

## Contract and deployment order

Deploy the companion RoomQuestGame database migration before this collector.
It introduces `community_collector_geocoder_claim_v2(p_token, p_limit)` and keeps
the old claim RPC US-only, so an old worker cannot lease a UK job. The collector
token is injected by the existing scoped RPC transport; no service-role key or
new credential is used.

Each v2 claim supplies `venue_key`, `query_text`, `lease_id`, `claimed_until`, and
an explicit `country_code` of `US` or `GB`. Missing or unsupported country values
stop the batch before reserving quota or calling Geocodio. GB queries contain
exactly three fields: the reviewed street or premises, town, and full postcode.
The postcode is normalized to uppercase with one space before its last three
characters. This validates a full postcode's format, not its existence.

Reserve, submit, and fail payloads carry the claim's country and, for GB, its
exact `query_text`. A GB reservation
must echo both the exact claimed query and `country_code=GB`; a mismatch stops
the batch without a provider request or a replacement address. The database
must independently bind those fields to the lease and reservation. Existing
US reservations without the new echo fields remain compatible.

Enable or queue one reviewed GB identity through the supported Admin workflow
only after the backend migration and this collector's production deployment are
verified. The companion Admin/database change owns exact event-to-venue review
and location-only queue eligibility. This collector neither selects a new venue
nor unpauses a source, changes publication approval, registers a feed, or fills a
source-wide default address. A geocoder resolution or updated staged record is
not evidence of a public Events card or Map pin.

## Provider request and result acceptance

The existing `https://api.geocod.io/v2/geocode` endpoint already supports the UK.
US requests retain `country=USA`; UK requests specify `country=GB`. The Bearer
key, two-result limit, eight-second timeout, response-size limit, no redirects,
and no automatic HTTP retries are unchanged. No field appends or alternate
provider are introduced.

Every accepted GB result must report `address_components.country=GB`. The full
alphanumeric `postal_code` is retained. GB's `nation` is not treated as a US
state. The first provider-ranked coordinate and its original accuracy fields
are retained under the existing finite-score and coordinate checks:

| Provider precision | Required GB address evidence |
| --- | --- |
| `rooftop`, `point` | Same street; the supplied building number must match; a present provider postcode must not conflict; same town or exact full postcode for a postal-town alias. |
| `street_center`, `range_interpolation`, `nearest_rooftop_match` | Same street and town, or same street and exact full postcode for a postal-town alias. A point elsewhere on the same street may have a different postcode. |
| `place`, `intersection` | Same town; provider postcode may be missing or different. |
| `county`, `state` | Rejected as before. |

The reviewed venue name remains a separate database identity. A postcode never
authorizes replacing its street or assigning a different staged venue's address.
An unnumbered street address does not acquire an invented building number.

GB HTTP 403 becomes the fixed `provider_country_access` reason. The database
holds that individual job without the US-wide authentication pause; the worker
stops the current batch after recording the failure. It records an access
rejection without claiming its cause is a missing plan or agreement. HTTP 401
retains the existing authentication failure behavior for both countries. No UK entitlement,
subscription, contract, or plan change is performed. US authentication failures,
rate limits, existing quota reservations, and other bounded retries keep their
previous behavior.

## Ordinary verification and bounds

Vercel's existing cron calls `/api/geocode` every minute. Its route invokes
`venue_resolver.run_pipeline`, which runs geocoding first on every tick and then
the existing optional venue/photo rotation. The function budget remains 60
seconds; the geocoder retains the 45-second batch deadline, ten-request maximum,
and 20-second reserve for each remaining request. No manual dispatch is needed.

Focused local verification:

```sh
python -m unittest tests.test_forward_geocoder
git diff --check
```

The 51 tests cover all existing US address, ZIP, suite, precision, quota,
deadline, endpoint-auth, and redacted submit-failure cases, plus full UK postcode
normalization, wrong-country and precise-postcode rejection, approved coarse
precision, immutable reservation bindings, scoped RPC authentication, and a
single held country-access failure. All provider and database operations in
these tests are mocked; fixtures do not supply production coordinates.

## Primary references

- [Geocodio API 2.0 UK release](https://www.geocod.io/updates/2026-06-10-introducing-api-20-with-support-for-the-uk)
- [Geocodio API reference: country and UK result fields](https://www.geocod.io/docs/)
- [Geocodio country support and UK access requirements](https://www.geocod.io/guides/country-support)
- [ONS postcode structure](https://www.ons.gov.uk/methodology/geography/ukgeographies/postalgeography)

Implementation and mocked test success are not a deployment or a successful UK
provider receipt. Record those separately in EVE-150 after ordinary live work.
