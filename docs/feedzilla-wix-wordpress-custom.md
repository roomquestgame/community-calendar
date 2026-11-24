# EVE-159 — Public Wix Events and WordPress custom event extraction foundations

November 24, 2026 · additive collector-parser code, **not a deployed Feedzilla
registered source**, source adapter authorization, or publication result.

## Wix Events public embedded data

`roomquest/wix_public_events.py` generalizes the previously
source-specific Wix Events warmup-data parser:
- Accept only a current publisher page containing the public Wix Events
  `wix-warmup-data` app ID and a declared, **complete** inventory
  (`totalCount` or `total` exactly equals the items, and `hasMore` is not true).
- Match each widget event to the *actual* first-party event-details link
  and exact published title/slug.
- Require explicit publisher country, complete physical address, venue and
  timezone, absolute dated event instances; use a maximum 60-day window.
- Skip individually cancelled/non-public/private/member-only items rather
  than exposing ticketed or private content.
- Do not fetch or invent Wix backend API endpoints, install Wix plugins,
  or assume the presence of Wix Events when a site uses the Wix CMS custom
  collections or an external ticketing system.
- A widget without full pagination evidence is **held**, not accepted as a
  zero-event or first-page-only source.

This deliberately does **not** yet cover Omnibus Theatre's multi-performance
Wix CMS pages or hidden custom datasets. A separate *first-party verified*
custom CMS schema or official public REST source is required before the
original London receipt #1222 can pass.

## WordPress public custom post types

`roomquest/wordpress_custom_events.py` supports a verified public
WordPress REST route such as a publisher-advertised `/wp-json/wp/v2/events`
or `?rest_route=/wp/v2/events` with explicit *reviewed* field mappings:
event-specific start/end date, venue, full address and optional occurrence
list. Unlike WordPress's post `date` or `modified` fields, these fields
identify the actual event schedule. A custom post type that exposes only
publication dates is **not** a calendar source.

The parser receives all pages with a proved WP `X-WP-TotalPages`-equivalent
count; it rejects a missing page, a changed post under duplicate ID, a
mismatched post type, ambiguous time zones or recurrence, foreign event
links and incomplete venue facts. It emits separate stable occurrence
identities, each within a maximum **60-day window**.

This does not assume every publisher exposes the same meta keys; it requires
the exact mappings and a verifiable public collection on a per-publisher
Admin **provider profile**. The Python parser alone does not authorize
a new source, change rights, or establish that the WordPress route returns a
complete event inventory. Those checks are part of the future shared
registration + checkpoint worker integration, not migration-time SQL seed.

## Integration and release dependencies

1. Connect these Python parsing cores to the normal source-admin provider
   profiles and the existing robots-aware `fetch_publisher` transport.
2. Use a generic checkpoint state in a **small** database migration with
   source+lease+CAS restrictions. Do not append new venue IDs into the
   old giant immutable `fetch_checkpoint_profile` SQL function.
3. Normalize validated rows into EventQuest staging, category and overlays;
   the existing complete-snapshot and publication gates remain the authority.
4. Add publisher-derived positive and negative fixtures and focused runtime
   tests before promoting any parser to a live collector.
5. **No rechecks or resubmissions of London registrations #1217–1226**
   until all four owner-approved capabilities are integrated and verified,
   including generic multi-run pagination and full Craft/Spektrix coverage.

Focused synthetic fixtures:
`tests/test_wix_public_events.py` and
`tests/test_wordpress_custom_events.py`. These are source-code tests,
not successful runtime collections.

## Existing supporting modules

- `roomquest/wix_embedded_calendar.py` (reviewed Wix Events warmup source)
- `roomquest/virginia_wix_events.py` (source-specific Wix HTML+JSON-LD)
- `roomquest/wordpress_capabilities.py` (published WP REST discovery)
- `roomquest/registered_html_calendar.py` (bounded HTML + explicit detail)
- `roomquest/feedzilla_pagination_checkpoint.py` (shared uncommitted
  DB-integration interface in companion PR #483)
