# Battersea Bloem public workshop fixtures

Captured November 22, 2026. `manifest.json` records exact original URLs, byte
counts and SHA-256 hashes. Raw captures remain local investigation evidence and
are not duplicated in this repository.

- `workshop-envelope.json` retains the real Duda page identity, one original CSS
  marker, the `dmBody` container classes, workshop heading and official Square
  link. Unrelated markup, styles, analytics and widgets were removed.
- `workshop.html` wraps the same retained publisher nodes as a normal HTML page,
  preserving the canonical URL found in the separately captured HTML response.
- `square-home.html` retains the published bootstrap's store identity, public
  active home-page structure, visible featured-events block and selected IDs.
  Unrelated commerce settings, themes, analytics and merchandise are removed.
- `square-events.json` retains all seven returned products, complete pagination,
  identity/schedule/location/price/availability/image fields and historical
  creation dates. Long narratives are replaced by explicitly synthetic text.

These are reduced source fixtures, not permission to access another store or
new source. Square's observed published GET loader has `editor` in its route;
the captured request was public, unauthenticated, and fetched only the exact
event IDs selected by the published storefront. No account or checkout was used.
The adapter continues to use ordinary robots, pacing, DNS and response bounds.

The captured static `timezone_info` offsets are deliberately retained, including
three stale summer offsets. Event dates and `Europe/London` determine the actual
offset. Legacy numeric `site_product_id` values remain distinct from Square's
new alphanumeric `id` values. All stock counts are retained as source evidence
but are not exposed as live availability; four sold-out flags are not treated
as cancellations.
