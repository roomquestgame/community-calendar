# Private Geocodio candidate review — November 22, 2026

## Observed problem and approved scope

Ben directed the five-registration recovery batch, including accepting Geocodio's
actual venue coordinates for Echo Dallas, original registration 338/source 6125.
Its single request `25c7d671-7b73-426f-8380-e355ab9991c6` completed as ambiguous at
01:06:43 UTC. The cache and exact Vercel request log retain no provider candidate
coordinate, so that historical result cannot be recovered or honestly accepted.
The original worker already accepted usable provider-ranked precision tiers;
this change does not claim that a stricter confidence threshold caused the hold.

## Change

An unsuccessful HTTP-success response can now attach its first US candidate to
the existing authenticated failure payload, strictly as private review evidence.
The allowlist contains latitude, longitude, accuracy, supported precision type,
US country code and a two-letter state code. Values must have the expected types,
finite numeric ranges and fixed codes. The candidate is included only for a
result-mismatch diagnostic; malformed results, other countries, county/state
centroids and arbitrary provider fields are excluded.

No formatted address, venue name, request URL, provider error text or complete
response is included. The structured console failure record explicitly removes
the candidate and retains its existing flags. The companion database change
independently validates the candidate and stores it only for active, approved
public staged-address demand in the existing private cache. It strips candidate
coordinates from GB/Geoapify failures and does not expose a new public API.

This diagnostic never resolves a cache entry, writes event coordinates, changes
verification, or schedules a provider call. Existing country/query binding,
reservation, attempts, quotas, backoff, HTTP limits and acceptance stay unchanged.
The old backend safely ignores the optional candidate, making collector-first
deployment compatible.

## Verification

`python tests/test_private_geocode_candidates.py`: nine no-network tests pass.
They verify first-result provenance, acceptance unchanged, type/range/finite
validation, country/precision guards, private RPC forwarding, console redaction,
and exactly one HTTP attempt on failure. Test coordinates are explicitly synthetic.
Another 47 unchanged validation, GB matching, diagnostic and submit-failure tests
pass against the actual modified geocoder, with unrelated import I/O boundaries
stubbed locally. This was a focused class selection, not the full provider suite.
The companion SQL preparation passes 47 PGlite groups covering unchanged private
ACL/security metadata, independent candidate validation, normal reservation and
failure recording, non-demand/GB exclusion, and the exact retry's negative guards.

No routine GitHub tests or workflows were enabled or dispatched. No provider
request, live cache mutation or public-event publication occurred in preparation.

## Handoff and release order

1. Merge this collector patch through its PR and verify a production READY
   deployment on the exact merged SHA with the existing collector aliases.
2. Only then release the companion `RoomQuestGame` migration
   `20261206191000_reviewed_feed_recovery.sql` through the protected deployment.
   Its exact Echo retry preserves attempt 1, original next-attempt timestamp,
   original failure evidence and request/quota ledgers; the ordinary worker
   alone claims and reserves the next provider request.
3. Observe that single normal retry. If resolved, verify subsequent publication.
   If still ambiguous with an actual plausible candidate, use the existing
   authenticated Admin venue-location override with the provider evidence under
   Ben's instruction. Do not invent a point, replace the selected candidate,
   mark failed evidence resolved, or trigger another paid retry automatically.

READY and live provider/publication acceptance remain separate release receipts.
The companion app journal records the final merge/deployment and recovery outcome.
