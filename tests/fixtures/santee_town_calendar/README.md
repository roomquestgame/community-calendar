# Town of Santee calendar fixtures

Reduced from the same batch's unauthenticated public publisher responses on
November 8, 2026. No new requests were made for fixture creation. Exact capture
times were not present in the retained receipt and are not invented.

The capture manifest records the original index, feed and event-detail byte
counts/hashes, available response receipts and reduced fixture hashes.

- The calendar index retains its canonical URL and the observed Drupal
  full-calendar configuration, including the exact public feed and parameters.
- The JSON feed is retained byte-for-byte. It supplies the named parade, stable
  event ID 314, canonical detail path and explicit local start/end offsets.
- The detail retains canonical identity, title, the calendar-event node, its
  explicit time elements and event-poster URL. A generic site-image meta tag and
  the Town Hall footer are deliberately retained as exclusion controls.
- Analytics, unrelated menus, cookie controls and forms are excluded.

The original Drupal document also uses its event-type CSS class on the body.
Parsing targets the actual full-view event div, avoiding both footer address
inheritance and accidentally treating the whole page as a second event node.
Unreduced index/feed/detail replay was checked against the reduced fixture and
produced the same normalized record.

The official schedule is December 12, 2026, 4–6 p.m. America/New_York. The event
page and reviewed poster do not supply a route/gathering address. Ben authorized
an explicitly approximate town-center fallback for a town-run event without an
address. The approved Census town center is 33.484582, -80.48998, geoid 4563790.
The record labels it reviewed_town_center_fallback / approximate, uses an empty
street address and the exact public explanation:

> Approximate location: Santee town center. The publisher has not supplied an event address.

This is owner-approved location review evidence, not publisher GPS or a claim
about the parade route. Explicit event addresses in the body, Drupal address
fields or matching Event JSON-LD take precedence and require normal geocoding.
Third-party, offsite or online listings cannot acquire the town fallback.

The parser only uses injected guarded transport. It verifies the calendar
contract, requests bounded date parameters, applies the exact rolling 60-day
window, cross-checks every detail date/time/title/URL, and preserves failures as
failures. Date-only entries are not assigned clock times. The poster remains a
publisher image candidate for the normal media-validation pipeline.
