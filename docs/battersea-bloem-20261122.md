# Battersea Bloem workshops — November 22, 2026

## Problem and exact scope

The normal registration request for
`https://www.batterseabloem.com/workshop` returned HTTP 200 with a Duda/IONOS
rendered-page JSON envelope despite its `text/html` response header. The generic
classifier correctly held it as `unrecognized_json`: this envelope is not an
event feed. Requesting `text/html` returned the equivalent page markup.

The new adapter applies only to that exact original URL and its existing
`source_key()` identity. The reviewed-listing fallback handles its envelope
locally; recurring HTML collection uses the same adapter. Generic JSON
classification, robots policy, headers, redirects, pacing, deadlines and other
sources are unchanged. West Hub is not included.

## Published evidence and bounded collection

Both original-page representations must identify the exact workshop page and
contain its actual link to `https://battersea-bloem.square.site/`. The adapter
then reads the public Square home page and parses its JSON bootstrap as data.
It verifies the published store, merchant and GBP currency and selects only the
active featured-events block's current product IDs.

The published storefront's shipped JavaScript uses a public, unauthenticated
GET loader beneath `/app/store/api/v28/editor/users/139773107/sites/282506720780254463/products`.
The reviewed path is allowed by Square's robots policy. The adapter constrains
that loader to this exact owner/site/merchant, `product_type=event`, page one and
the selected IDs; it does not scan the catalog or follow pagination. The complete
response must match the selected set without missing, duplicate or extra items.
The original page, Square home and one products response are the only content
requests. Each goes through the existing robots-aware transport and shared
deadline. Limits are 20 featured IDs, 1,000 URL characters and 3 MB per parsed
response; access denials, incomplete collections and unverified data remain holds.

The source's `Crawl-delay: 5` is honored by the existing pacing helper. A cold
robots reservation and the two subsequent Square reads fit the normal 35-second
registration budget when publisher response time permits. Insufficient time
preserves the existing deadline/defer behavior; the adapter has no retry loop.

## Event contract

The November 22 capture contains seven explicitly dated 2026 sessions: six wreath
workshops at £48.50 and one table-arrangement workshop at £37.50. Four have a
sold-out badge. Product creation dates are older and do not supply event years.

The collector retains `site_product_id` as `battersea-square:<id>` because legacy
IDs 88, 130 and 90 differ from the Square catalog IDs. Each occurrence links to
its actual HTTPS Square product URL. Structured start and end dates/times use
`Europe/London`; three cached editor timezone offsets are stale, so they are not
used. The observed string `has_no_end_time='0'` means the explicit end exists.

The publisher's two split address representations are verified and normalized
to `10 Hamilton Road, Cambridge CB4 1BP, United Kingdom`, venue `Battersea Bloem`.
Other addresses are rejected. Coordinates remain null for normal geocoding.
Sanitized public narrative, an explicit price sentence and an optional
`Tickets sold out.` note use the existing 2,000-character description contract.
Sold-out sessions are retained and are not marked cancelled. Inventory settings
do not establish precise remaining ticket counts.

An unsigned thumbnail from this exact store can be returned as an ordinary
image candidate. The adapter adds no native-content evidence, provider profile,
media authorization or image request. Existing backend media gates decide
whether any candidate is retained or displayed. The normal worker capability is
`publisher_event_candidates_v1`.

## Verification and release boundary

The reduced fixtures record capture URLs and SHA-256 hashes and retain all
seven identities, schedules, address forms, prices, stock flags and image facts.
Long narratives are replaced with marked synthetic prose. A separate offline
replay of the full captured publisher responses produced identical seven-event
results from both original-page representations.

Focused local checks:

```sh
python -m pytest -q tests/test_battersea_bloem.py tests/test_feed_registration.py tests/test_uk_registered_listings.py tests/test_registered_listings.py
```

These cover real registration and recurring dispatch, dynamically changed
featured selections, complete results, wrong store/domain/venue, malformed
payloads, missing years and invalid times, stock and price handling, denial at
each read, bounded requests and real pacing with a fake clock. Network and
registration RPC effects are stubbed. They establish parser and dispatch
behavior, not production deployment or publication.

The companion backend change must add the exact URL to the existing reviewed
listing helper and its exact UK venue profile. After the normal releases,
recheck the existing Admin receipt 877 and verify actual source, venue and event
results through the existing pipeline. This collector change does not create or
reactivate a source, write a database row, deploy code or publish an event.
