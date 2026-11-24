# EVE-159 — WordPress native-first calendar discovery

**November 23, 2026. Implementation branch only; not a deployment receipt.**

## Intent

Avoid new venue-specific HTML collectors whenever an actual WordPress event
subscription/API exists. Sites may run an updated WordPress core with a
decade-old custom plugin; never infer a calendar plugin/version from the
WordPress generator version alone.

Native-first precedence for a registered, unfiltered calendar page:

1. Existing publisher-linked first-party ICS, TEC JSON, Squarespace and other
   validated subscriptions keep their established precedence and identity.
2. The existing TEC HTML signature may propose its documented TEC REST route.
   When HTML advertises a `rel="https://api.w.org/"` root, use that exact root:
   both `/wp-json/` (including subdirectory installs) and `?rest_route=/`
   permalink mode are supported. Retain the old documented TEC path fallback
   only when HTML does not advertise a REST root.
3. For unrecognized calendar pages that advertise a root, fetch that single
   actual first-party WordPress API index and check its advertised namespaces,
   routes and GET methods. Only an advertised
   `/tribe/events/v1/events` GET route may enter the **existing** TEC
   classifier and registration/normalization/collection path. Validate the
   actual collection body before selecting it; existing
   `recover_html_feed()` then performs its event parse probe before
   registration. `wp/v2/types`/custom post types alone cannot register.
4. Without a usable event-specific API, keep the existing complete, bounded
   HTML-calendar validation and hold/retry behavior. No partial snapshot
   becomes an authoritative replacement and no missing date/venue is invented.

No new source, adapter kind, scheduled worker, database schema, API credentials
or publisher-rights bypass is introduced. The page must be an unfiltered,
calendar-like URL, and the API root must be advertised by that publisher.
The existing request/robots/pacing/host/deadline limits remain unchanged.
Native API-index probing is capped to one root plus one proven event endpoint,
within the original four-request/two-machine-check locator budget.

## Capability families (recognition is not extraction)

`roomquest/wordpress_capabilities.py` can identify HTML signatures for TEC,
Events Manager, Event Organiser, Modern Events Calendar, EventON, WP Event
Manager, legacy All-in-One Event Calendar and legacy JSON API. A WordPress
REST index identifies `wp/v2`, `tribe/events/v1`, `mec/v1.0`,
`events-manager/v1`, and vendor `eventon` / `wpem` namespaces when
actually present. It separately reports event-like publicly readable custom
post type REST routes and whether `/wp/v2/types` exists.

Those non-TEC interfaces are **inspection only** until a reusable adapter
can prove genuine start/end, local timezone, recurrence, original URL, venue,
complete listing scope and publisher access. Ordinary WordPress `date`,
`modified` or RSS publication timestamps are not event start times.
The event page's WordPress 5.5+ JSON alternate can be a useful detail clue,
not proof of a complete calendar. Events Manager ICS and other existing
publisher-linked feeds remain eligible through the established ICS parser.

### Historical compatibility references

- WordPress official REST discovery, including 4.4–4.6 index-only,
  `wp/v2` from 4.7, `Link`/HTML rel discovery and 5.5+ per-document JSON:
  https://developer.wordpress.org/rest-api/using-the-rest-api/discovery/
- Registered custom post types require `show_in_rest`, with their own
  `rest_base` and optional `rest_namespace`:
  https://developer.wordpress.org/rest-api/extending-the-rest-api/adding-rest-api-support-for-custom-content-types/
- WordPress REST pagination uses `page`, `per_page`,
  `X-WP-Total` and `X-WP-TotalPages`:
  https://developer.wordpress.org/rest-api/using-the-rest-api/pagination/
- REST post-type metadata is discoverable through `wp/v2/types`:
  https://developer.wordpress.org/rest-api/reference/post-types/
- TEC REST: https://dev.theeventscalendar.com/knowledgebase/introduction-to-the-events-calendar-rest-api/
- Events Manager ICS: https://wp-events-plugin.com/documentation/event-ical-feeds/

## Focused verification

`tests/test_wordpress_capabilities.py` covers safe root discovery, HTTPS and
same-host rules, legacy query-permalink and subdirectory modes, historical
plugin fingerprints, GET-only TEC route validation, non-TEC/CPT rejection,
the existing registration-to-TEC collection path, and filter-scoped holds.

Run focused local tests if the full checkout is available:
```sh
python -m pytest -q tests/test_wordpress_capabilities.py tests/test_feed_registration.py tests/test_wordpress_adapter.py
```

The first isolated capability module fixtures were also reproduced in a
standalone Python workspace: **17 passed**; that does not substitute for
the integration suite, publisher-site checks or production receipts.

## Original ten London registrations

Retain IDs 1217–1226; **do not resubmit or force recheck**. Target the seven
identified/likely WordPress sites first: 1217 Poplar Union, 1218 Oxford House,
1219 Horniman, 1220 Conway Hall, 1223 Spitalfields Music, 1224 Museum of the
Home, 1225 South London Gallery. Inspect actual advertised API roots and
routes, not guessed plugin paths. Confirm a genuine future event with venue
and occurrence time through normal Admin Preview before marking any source
registered, and confirm public publication separately. Custom WordPress
calendar extraction, legacy JSON normalization, API token integrations and
resumable pagination are separate remaining capabilities; this code does
not claim to unblock all seven.

**Operational release boundary:** Collector PR review and deployment from
the exact merged source SHA, then original-ID Admin technical recheck (the
current recheck RPC has narrow eligibility). Do not run routine GitHub
CI, create migration-based source records, weaken publisher robots policy or
publish new events simply because the REST index exposes a route.
