## November 24 — owner reiterates trust of provider points

Owner explicitly requires accepting the geocoder's returned matching point
without an arbitrary minimum confidence. Geocodio already accepts scores
0–1; Geoapify had a .8 threshold in Python AND the SQL verifier. Remove that
floor in both, retain the native numeric confidence, precision and
attribution; no change to existing identity, country, supported precision,
credential/lease, quotas or invalid-response checks. Littleport #6374 actual
Geoapify request 1bc71082-106e-4f2b-b2a3-a461e64f5a80 was ambiguous solely
in recorded score_valid, with one address/country/coordinate/type match;
the precise returned score/point was not saved. Preserve provider history.
After both releases, retry only the existing eligible Littleport address
without resetting attempts or issuing an out-of-band request. No batch
requeue, no new cron, queue, geocoder or broader source-policy changes.
30/30 focused Geoapify unittest cases passed on exact GitHub blobs in
network-denied sandbox, including 18 low/high score and precision cases,
unchanged native coordinates/attribution and malformed/mismatch negatives.
Shared Supabase rollback tests passed. Release DB first, then collector.
Historical .8 threshold below is superseded.

---

# Geoapify for reviewed UK venue addresses

The reviewed UK feed test reached Geocodio but received HTTP 422 responses under
the current account. The owner chose a Geoapify account for UK coordinates.
This change uses Geoapify for `GB` jobs when explicitly enabled, while US jobs
continue using the existing Geocodio adapter and credential.

## Production configuration and release order

| Variable | Purpose |
| --- | --- |
| `GEOCODIO_API_KEY` | Existing server credential for US requests. |
| `GEOAPIFY_API_KEY` | Geoapify server credential, scoped to the collector's production environment. |
| `GB_GEOCODER_PROVIDER=geoapify` | Selects the new GB provider and provider-aware claim contract. |
| `FORWARD_GEOCODER_ENABLED=true` | Existing worker switch; `VERCEL_ENV=production` remains mandatory. |

The default GB selector is `geocodio` for deployment compatibility. Adding the
Geoapify key alone does not switch providers. A selected provider without its
key stops before reserving quota or making an HTTP request; it never falls back
to the other provider. An unknown selector stops before claiming work.

1. Apply the companion RoomQuestGame database migration first. It accepts the
   Geoapify claim selector, binds each reservation and result to its actual
   provider, independently validates native Geoapify results, and stores source
   attribution and native precision. Its existing shared daily ceiling remains
   2,300 requests; the separate Geoapify hard ceiling is 3,000. Its reservation
   gate enforces at most five Geoapify requests per second and keeps Geoapify
   provider failures from pausing US Geocodio work.
2. Deploy the companion app attribution and precision display before exposing
   newly geocoded results. Persisted Geoapify coordinates require Geoapify and
   underlying data-source attribution, including on later cache reuse.
3. Configure the production-only Geoapify key and GB selector, keeping the
   existing US credential and worker switch. Do not put credentials in source,
   fixtures, diagnostic output, or a client-visible environment variable.
4. Deploy this collector. The existing `/api/geocode` cron and
   `venue_resolver.run_pipeline` run the same worker; no second worker or manual
   retry loop is needed. The batch remains bounded to ten attempts and 45
   seconds, with a 20-second allowance before starting another job.
5. Observe fresh provider-bound reservations, stored native Geoapify receipts,
   positive database submissions, and the ordinary staged-event updates. A
   successful geocode does not by itself prove that an event was published or
   that an Events card or Map pin is visible.

The provider-aware claim can make an eligible failed Geocodio GB job available
for Geoapify only through the companion database's ordinary demand, backoff,
attempt-limit and lease checks. It preserves earlier failure evidence and
successful cached coordinates. It does not reset a cache, move a venue, change
source review or publication approval, or register another feed.

## Bound request and result contract

With the Geoapify selector, a worker claim uses the existing authenticated
`community_collector_geocoder` gateway:

```json
{"p_action":"claim_v2","p_payload":{"limit":1,"gb_provider":"geoapify"}}
```

The scoped RPC transport supplies the existing collector token. With the
default selector, the existing `community_collector_geocoder_claim_v2` call is
unchanged. US reserve, submit and fail payloads remain unchanged in both modes.

For GB Geoapify jobs, reserve, submit and fail payloads carry
`provider="geoapify"`, the explicit `country_code="GB"`, and the exact claimed
`query_text`, in addition to the lease and venue identity. A reservation must
echo all three before HTTP is allowed. The response envelope carries
`provider="geoapify"` and a `results` array containing exactly one native result
object. Actual submissions retain the bounded native address evidence,
coordinates, result type, confidence fields and data-source attribution from
the first accepted result. They do not invent Geocodio accuracy fields or label
Geoapify results as Geocodio.

The adapter makes one GET request to
`https://api.geoapify.com/v1/geocode/search`, with the exact reviewed query,
`filter=countrycode:gb`, `bias=countrycode:none`, `format=json`, `lang=en`, and
`limit=2`. Geoapify requires `apiKey` as a query parameter. The worker never logs
request URLs or raw provider error text. Redirects are refused, the timeout is
eight seconds, and the response is bounded to 30,000 bytes.

Only the first provider-ranked candidate can be accepted. Every candidate must
have numeric finite coordinates, explicit lower-case `country_code=gb`, a
native confidence of at least 0.8, and one of `full_match`, `inner_part`,
`match_by_building` or `match_by_street`. All supplied confidence fields must be
numeric in `[0,1]`. The complete bounded source name, attribution, licence and
HTTPS source URL must be retained.

| Native result type | Required reviewed-address evidence |
| --- | --- |
| `building`, `amenity` | Same normalized street and either the same town/locality or exact full postcode. An expected house number must match; a supplied postcode must not conflict. |
| `amenity`, named-site alternative | No leading house number in the reviewed query; exact normalized amenity name after removing only one trailing parenthetical qualifier; exact full postcode. |
| `street` | Same normalized street and either the same town/locality or exact full postcode. A missing house number is allowed; the result retains its native street precision. |
| City, postcode, suburb, county, state, country or other result types | Rejected. |

The named-site alternative lets a canonical query such as `wandlebury ring`
match `Wandlebury Ring (Iron Age Hill Fort)` at its exact postcode. It cannot
match `Wandlebury Hill` or a nearby `Gog Magog Hills` peak merely because they
share that postcode. Street and amenity coordinates remain approximations at
their reported native precision, rather than being relabelled as a rooftop or
building entrance.

HTTP 429 produces `rate_limited`; HTTP 401/403 produces `provider_auth`;
400/422 produces `ambiguous`; other HTTP or transport errors produce a fixed
provider-error reason. Diagnostics contain only bounded enums, booleans,
counts and validated queue identifiers. No HTTP request is automatically
retried. A SQL `provider_rate_limit` reservation denial ends the batch without
HTTP or a consumed attempt, allowing the normal scheduler to continue later.
A submit transport failure never triggers a replacement failure or another
provider request. Geoapify counts as resolved only when the database returns
the boolean `resolved=true`.

## Focused verification

```sh
python -m pytest tests/test_geoapify_geocoder.py tests/test_forward_geocoder.py tests/test_venue_resolver.py -q
git diff --check
```

The local suite covers both provider routes, old US behavior, provider/country/
query binding, missing credentials, quota and pacing denials, precision and
address checks, malformed responses, credential-safe diagnostics, no retries,
positive database acceptance and the existing pipeline. The seven live
canonical UK response projections are recorded in
`tests/fixtures/geoapify/reviewed_gb_responses.json` for offline validation. All
seven pass and retain the provider's exact coordinates, native precision and
attribution; the nearby-peak negative case fails. These fixtures are never
imported by production code or used to fill production coordinates.

## Primary references

- [Geoapify forward geocoding API](https://apidocs.geoapify.com/docs/geocoding/)
- [Geoapify pricing and free-plan limits](https://www.geoapify.com/pricing/)
- [Geoapify attribution requirements](https://www.geoapify.com/terms-and-conditions/)
- [OpenStreetMap attribution and licence](https://www.openstreetmap.org/copyright)
