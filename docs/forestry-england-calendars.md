# Forestry England: complete forest calendar intake

Implemented 22 November 2026 for the all-forests source intake scope. This change
adds a shared Forestry England Drupal calendar extractor, not a pilot or a list
of seeded sources. Every source must still enter through the signed-in Admin
website and pass normal registration, collection, venue and publication gates.

## Scope and registration

`registered_html_calendar.supports_listing` and `collect` dispatch the reviewed
Forestry England layout to `roomquest.forestry_england`. The existing negotiated
HTML and native-content capabilities, `kind=html`, `platform_adapter=html`,
source-key hash and `registered_html_jsonld_v1` receipt remain unchanged. No new
adapter enum, source row, migration seed or workflow registration is added.

Only exact HTTPS `www.forestryengland.uk` calendar URLs with no query or fragment
can qualify: forest `/venue/events[-slug]` paths, forest `/events` paths, and
observed Drupal `/node/<id>` calendars. The document must independently prove
its canonical URL, `page-node-type-venue`, an `Events at/in …` heading and the
unique rendered `Dates and events` view. Every card links back to the submitted
venue scope. Marketing hubs and single-event pages are not calendar sources.

The captured network contains 65 sitemap calendars plus Dodd Wood's explicitly
linked `/node/4636` calendar. All 66 pass layout recognition. An empty complete
calendar can be registered and collected as empty after the same complete
collector succeeds. This exception applies only to the verified Forestry
layout, preserving coverage for future local demand without inventing events.
Its normal native empty staging acknowledgement precedes a zero-count preview.
A text-only Facebook pointer does not authorize a Facebook crawl. Source region
coverage must still be assigned through the normal Admin workflow.

## Complete bounded pagination and deadlines

All observed Drupal pages complete before any detail extraction is returned.
Pagination changes only the zero-based `page` selector on the exact original
calendar path. Its current-page marker, next link, numeric inventory, canonical
URL and eventual complete page set must agree. Cross-host/path selectors,
ambiguous next links, missing pages, cycles, repeated inventories and limits
hold the entire source; no successful prefix is returned.

Forestry-specific limits are ten listing pages, 100 unique details and 500
normalized occurrences, with the existing 3 MB HTML and structured-node bounds.
Other HTML publishers retain their current three-page/20-detail limits. The
normal protected transport, robots policy, pacing and worker deadlines remain
unchanged. No headless browser, guessed API or parallel publisher fetch is used.

The current largest calendar, Westonbirt, has 31 cards across four pages. A
listing card can avoid its detail fetch only if its displayed explicit date
agrees with its machine date and proves that all listed dates start beyond the
normal 60-day horizon. The parser still visits every listing page and records
every omitted URL. Ambiguous and recurring cards always get their detail
checked. In the captured window this leaves 15 details plus four listing
requests, without splitting or shrinking the registered source scope.

## Actual occurrence dates

Forestry England's Event JSON-LD often publishes a season/series envelope and
an editing-time placeholder clock. Its canonically matched visible date/time
fields therefore supply session clocks; JSON-LD supplies the anchored dates,
identity and actual venue. Listed month/day dates are resolved only within
their dated grouping, and any supplied weekday must agree. The event's own UK
venue facts justify `Europe/London`; the shared normalizer handles DST and
rejects ambiguous/nonexistent local times. A registration/opening clock is not
substituted for an explicit run/race start.

Supported schedules include single dated events, ordered multi-date lists,
daily and weekly programs with fixed times and bounded published dates,
weekday/month restrictions, anchored fortnightly programs and explicitly
listed multiple sessions. Starts are distinct occurrence identities; the
collector does not invent an end time when none is supplied.

A canonical, ordered visible date list may extend beyond a stale JSON-LD end
date only when explicit years or a weekday-checked annual grouping resolve the
dates. Such discrepancies are diagnosed. The captured Westonbirt willow
workshop lists Saturdays through December 2027, while schema `endDate` stops on
20 February 2027. Its 12 December 2026 session is safely inside both, and later
explicit dates retain their own authority instead of turning the schema range
into a continuous event. Conflicting weekdays, invalid calendar dates, source
identity or venue facts still hold the collection.

Fully fetched but genuinely untimed or unresolved activities are ineligible,
with URL/reason diagnostics. Examples include selected evenings with variable
entry slots, term-time classes without holiday exceptions, unspecified
alternating weeks and all-day content unsupported by the current timed event
contract. These exclusions do not erase other complete dated events. Seasonal
Christmas trails are never expanded into invented daily admission slots.

## Full native descriptions, venue facts and rights

The matching detail must have one canonical URL, Drupal event type, an agreeing
H1 and Event URL/title, and both visible venue link and `Event.location.url`
matching the exact source calendar. Venue names, address lines, postcode,
country and coordinates come from that Event's own location. Missing locality
is preserved as missing; no town, street or map pin is invented.

The unique `main .field--name-body` supplies the full native narrative when the
structured summary is contained in it (ignoring only HTML text-boundary and
punctuation normalization). Conflicting or ambiguous bodies hold the source.
The proof uses `description_field=forestry_event_description`, the actual fetched
`evidence_url=event_url`, and the existing extraction marker. Sanitization and
the 12,000-character bound remain unchanged; overflow is held, not truncated.
The paired backend capability migration must recognize this narrow evidence
field before Admin registration/collection is released. Older source claims
without the existing capabilities do not activate this extractor.

Forestry England's [copyright notice](https://www.forestryengland.uk/article/crown-copyright)
permits website-information reuse under the Open Government Licence with its
Crown Copyright/Forestry England attribution. Logos, images and identified
third-party material are excluded. **No native image candidate is staged.**
This implementation does not establish third-party image permission or bypass
the ordinary source/content rights gates.

## Evidence and release

The fixture manifest covers all 66 scopes, all 70 listing pages and 123 exact
linked details. Raw captured-response replay produced 228 eligible occurrences
across 19 calendars; 47 returned no extractable timed events. These are observed
capture results, not promises that all future publisher content is eligible.

Focused tests include all 66 scopes, four-page completeness, source-preserving
horizon filtering, registration and recurring worker dispatch, full native
proof, UK venue pins, DST, multi-session identities, seasonal/term-time/all-day
exclusions, schema-envelope discrepancy precedence, transport failures,
deadlines, scope escapes and narrative identity/length guards. Run:

```sh
python -m pytest tests/test_forestry_england.py tests/test_registered_html_calendar.py tests/test_registered_native_content.py -q
```

The local production-transport probe stopped immediately with `dns_unavailable`
before any publisher contact. The guard was preserved. A successful deployed
registration/collection receipt is still required; fixture replay alone is not
a production registration. Deploy the collector and matching native evidence
allowance, then submit all desired forest calendar URLs through Admin. Verified
empty calendars retain their exact source scope and zero-event outcome for
future collection; this exception does not make missing/failed pages healthy.
