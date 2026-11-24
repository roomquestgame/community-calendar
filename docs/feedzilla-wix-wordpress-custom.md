## November 24 — provider-only scope revision and real UK Wix shadow

Owner coordination: Feedzilla may modify only provider-specific parsing,
extraction, profile evidence and checkpoint adapters. Shared transport,
publication, scheduling, deduplication, ETag/fingerprints, Admin lifecycle,
coverage, venue-processing performance and robots policy belong to the
ICS/Supabase workstream. Do not use the proposed separate database checkpoint
migration described in the historical section below; use existing shared
checkpoint/claim/stage/complete interfaces after the owner of those facilities
confirms an admission contract. PR #489 remains on coordination hold and
central Spektrix stays disabled. No London original receipt rechecks.

**Provider-only changes.** Custom WordPress extraction now validates an
ordered prefix of exact page-URL receipts, page lengths and publisher
X-WP-Total/TotalPages values (including conflicting case-insensitive names);
the next page is derived only after a valid prefix. Complete extraction
delegates to the existing event parser. The ordinary shared fetch returns
body text/bytes, not actual HTTP headers/final URL; provider integration is
blocked pending shared transport-owner support, not a separate network
client or persistence mechanism. No new registration or checkpoint
authorization. Wix validates contradictory declared counts and non-boolean
pagination/status/visibility evidence, detects conflicting case variants of
a publisher UUID, honors explicitly hidden end dates as in the previously
reviewed Wix adapter, and accepts the two actually observed first-party
detail-link families /event-details/ and /event-details-registration/.
No new visibility enum guesses or relaxation of inventory proof.

**Read-only publisher evidence:** two independent UK calendar leads, no
matching registration/source domains in the read-only production check.
Both exact robots.txt URLs returned 200; current collector policy parser
allowed the exact listing, crawl-delay 1, then a single bounded first-party
GET per site. No API calls or alternate user agents; no source registration,
retry, staging or publication. 
- https://www.stephnorwood.co.uk/upcoming-events (Cambridgeshire): 5 embedded
  records, 4 dated physical UK events Dec 9–17, one explicitly TBD; 10
  observed detail anchors (title + Details), /event-details/. The visible
  listing has hasMore=false but neither totalCount nor total. All embedded
  registration.restrictedTo values 0, distinct from the current reviewed
  synthetic/legacy 1. Strict extractor holds wix_public_pagination_unverified.
- https://www.breathbodysoul.co.uk/upcoming-events (London): 7 embedded
  records, four dated physical UK events Dec 6–Jan 17, one online and two
  outside the current window; 14 detail anchors with /event-details-registration/.
  hasMore=false but no totalCount/total, same numeric visibility 0. Strict
  extractor holds wix_public_pagination_unverified. Vendor symbolic
  VISITOR/MEMBER documentation is not proof of warmup numeric enum mapping;
  require actual evidence before changing eligibility or filtering.
- Both leads are candidates only. Need independent complete-list evidence
  and exact numeric visibility semantics, then normal authorized Admin
  intake. No forced type hints, hidden endpoints, token use or source writes.
  Explicit publisher TBD/online/mixed-country behavior needs reviewed
  provider-specific handling before admission.

**Verification:** 43 focused direct assertion cases on five SHA-verified
GitHub blobs: WP core 7, WP pagination 17, Wix 19. Python 3.14.4 with
repository-pinned BeautifulSoup 4.15.0 in temporary Vercel sandboxes.
pytest absent; assertion cases executed with standard-library raises and
parametrize harness, not full pytest/CI. Both sandboxes stopped. The real
shadow was a read-only, exact-policy/DNS/no-redirect limited diagnostic,
not a deployed collector or a successful complete import. Required
.claude/bram-conventions.md was 404 on current main; AGENTS.md and existing
provider contracts used. No migration or shared-file change. Do not deploy
standalone dormant parser work while shared rollout is active; coordinate
release without changing processing fingerprints. EVE-159 tracks scope.

---

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
