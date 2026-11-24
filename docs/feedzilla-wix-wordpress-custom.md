## November 24 — EVE-159 durable generic HTML checkpoint integration

Owner-authorized integration of PR #490's tested generic HTML request stream with existing registration receipts and ordinary HTML worker leases. No new queue, scheduler, credentials, publication pipeline, or source IDs. Collector branch `feature/eve-159-durable-html-admission-20261124`; backend branch `feature/eve-159-html-checkpoint-admission-20261124`, migration 20261207036000. Capability negotiation gates collector code until backend rollout. Existing receipt retains revisioned compressed fetch-only state; verified terminal receipt transfers to an exact newly queued registered source. Existing source checkpoint, native staging, publication, access and publisher wait controls remain authoritative. Valid partial capture may continue past six registration attempts; ordinary retries remain capped. Maximum eight requests per claim, existing four-hour/500-task/12MB-expanded/850KB-compressed bounds. No records are staged from partial captures. 24/24 focused Python tests passed; simulated 54 requests across seven claims, 45 records, zero extra GETs on first source replay. Migration rollback-only shape/lease/retry/ACL tests passed, plus temporary invoker clones of gateway bodies tested CAS, partial rejection, second claim, terminal registration and exact source transfer; test-only token predicate, no live credential changes or committed fixture. SQL delimiter and harness transfer issues corrected; sandbox stopped. Collector's optional .claude/bram-conventions.md unavailable (404). No routine CI, no production registration reset, no +500 rollout. Release order: collector production SHA and alias verified, then protected DB migration; verify ledger and actual first-registration canary before rechecking original London receipts. Live end-to-end worker completion remains unproven.

## November 24 — owner-authorized scoped provider release

- Littleport source #6374: normal third Geoapify attempt resolved the exact publisher address at 16:16:46 UTC with confidence 0.5; readback at 16:52 UTC verified one scheduled public event, 586b2f64-ab78-411c-b644-c9f7508d0f4a. Staged historical location reason remained held; do not equate that reason with no public row. Category sports needs separate category-rule review. A fresh first-registration canary remains necessary.
- Generic HTML request stream now shares the actual ordinary collection traversal; legacy one-run limits and Forestry exception are retained. A fetch-only authenticated ordered-prefix continuation entry point replays listing/detail evidence, returns the next exact request, and produces ordinary normalized rows only after terminal pagination and every detail. It consumes existing checkpoint bounds, does not persist/claim/stage/publish itself, and is not wired to the live registration dispatcher.
- Offline exact-blob Vercel sandbox with network denied, pinned BeautifulSoup: 30/30 focused tests passed twice (16 generic HTML, 14 native WordPress inventory). Real HTML/JSON-LD extraction, normalizer and native evidence validation exercised; four-page ordinary old/new output equality, 9 pages + 45 details / 54 unique requests with simulated continuation, selector/scope/order/limit/deadline and incomplete-detail negatives. New committed regression module rerun with native WordPress tests, 30/30. Actual preview-worker factual functions isolated; unrelated specialized provider branches and unused Tribe fallback isolated by fail-on-use sentinels. No full CI or authenticated live continuation claimed.
- Owner authorized release of tested provider-only changes. Shared EVE-170 migrations through 35000 are live, existing enrolled ordinary ICS scoped parser dependencies are unchanged. Non-scoped sources can need a fresh proof baseline on normal demand because the global parser package changed. No reauthorization, forced collection, queue reset or shared fingerprint modification.
- Remaining gates: registration-receipt-bound and registered-source-bound use of the existing shared fetch checkpoint claim/CAS/continuation mechanism; actual publisher pagination acceptance; guarded HTTP header/final URL support for custom WordPress; fresh Admin canary. No original London receipt rechecks, no new source activation, no central Spektrix access or +500 ICS. Do not claim this provider package is complete intake automation.

---

# November 24, 11:09 ET — follow-up publisher evidence

- St James's Church, Paddington: `https://stjamespaddington.org.uk/events/`.
  No matching live registrations or sources by domain. Read-only Vercel
  diagnostic with the collector's exact robots policy, user agents,
  crawl-delay handling, public DNS checks, bounded responses and no redirects.
  Robots 200, delay 1 second; listing advertises WordPress REST index,
  index advertises native TEC event route. Four requests total. 60-day
  window Nov 24–Jan 23, per_page=100: total=17, total_pages=1, 17 raw
  members with publish status and publisher address, Europe/London.
  Patched inventory guard accepted the complete one-page inventory.
  This is not an eligibility or end-to-end publication result.
- Sample venue street `Sussex Gardens, Paddington,`, locality London,
  postcode W2 3UD, country United Kingdom. Read-only production
  `shared_gb_raw_street` returned NULL for the composed literal and
  punctuation-cleaned address. Littleport control returned its expected
  street query. This candidate is not a clean automatic address-only
  geocode canary; route the address shape to shared venue-resolution
  ownership, do not change shared code or invent a street number.
- Community Links (www.community-links.org): no matching registrations
  or sources by domain. Robots 200, crawl delay 10 seconds. Diagnostic
  intentionally deferred before listing retrieval (local diagnostic
  delay budget <=5 seconds); not denied or invalid. A future paced run
  must honor the publisher's full delay. Both sandboxes stopped.
- No original receipts retried, no new registration, no publication,
  no live mutations, no added infrastructure. Still need real multi-page
  native inventory and a fresh normal Admin canary after Littleport
  publication proves the existing path. Draft #490 stays unmerged
  pending coordination with EVE-170 and shared venue ownership.

---

## November 24 — resume checkpoint: incomplete native TEC count declarations

Live readback 16:04 UTC: original London #1217–1226 remain seven review,
three retry (due Dec 24), all one attempt and zero linked sources. Littleport
#1230/#1231 → source #6374 approved/ready/complete, one staged held event
#454245, no coordinates. App #1914 and collector #491 are merged; prior
Geoapify retry consumed attempt 2 on the OLD deployment during alias cutover.
The existing normal retry is pending for 16:15:49 UTC; do not force/reset it.
No changes to original receipts or shared infrastructure.

Native registered TEC guard now rejects one-sided count declarations on any
page and late introduction of totals after a genuinely count-less first page.
Both could previously silently fall through legacy mode, accepting an
unproved inventory. Consistently count-less legacy responses still work.
Exact old/new class extracted by AST from the full GitHub blob, compiled
and run in a short-lived network-denied Vercel sandbox: reproduced three
old false acceptances, 11/11 isolated guard cases passed; patched provider
blob SHA 565d9949a5c1c698b1c09e579235ba9e093f9819. Sandbox stopped.
Added three collect-path regression tests; those new full integration tests
were not separately run. No routine CI or deployment. Keep #490 draft
pending real multi-page shadow, normal Admin canary/publication and
shared-owner transport/continuation agreement.

Two independent first-party potential native TEC leads found in public
listing research: Community Links (community-links.org/events/) and St
James's Church Paddington (stjamespaddington.org.uk/events/). Both have
future dated venue listings; production duplicate check found no receipts
or sources on either domain. Exact current collector robots policy, actual
advertised API and completeness have not been verified; do not submit or
claim either as a feed. No original source rechecks or +500 expansion.

---

## November 24 — actual permitted native WordPress collection; Admin blocker

Owner approved next batch: WordPress and provider pagination together, actual
automatic onboarding, not only parser recognition. Existing shared transport,
checkpoint authorization, hash/ETag/dedup, scheduling/publication, robots
policy, coverage/venue processing and +500 ICS remain the other workstream's
scope. Keep original London ten and ADC/Spektrix holds intact.

**Real independent publisher acceptance leads:** read-only DB duplicate
check found no source/registration domains for Bow Arts, Littleport Society,
Inside Cambridge, 2G3S Stapleford or IHRC. In short-lived restricted sandbox,
actual collector UA and unchanged robots matcher/delay, DNS and no redirect:
- The Littleport Society `https://www.littleportsociety.org.uk/events/`:
  robots 200 allowed, delay 1; publisher advertised `/wp-json/` and index
  explicitly advertised GET `/tribe/events/v1/events`. Exact bounded native
  API response for Nov 24–Jan 23: 1 raw member / total 1 / pages 1, no next;
  published Dec 1 Christmas Prize Quiz Night, Feoffees Hall, 28 City Road,
  Littleport CB6 1NG. A second fresh read using the actual revised
  wordpress_adapter.collect normalized one row with UTC 19:30,
  Europe/London and full street address. No source or staging write.
- Inside Cambridge `https://insidecambs.co.uk/whats-on/`: same genuine
  native API, 29 unique members / total 29 / pages 1. This is a multi-venue
  aggregator including ADC Theatre and Cambridge Corn Exchange. Do not submit
  it as an independent publisher or circumvent existing holds/overlap.
- Bow Arts listing: robots allowed/delay 3 but requested /events/ returned
  301; diagnostic did not follow an unreviewed redirect. Hold that lead.

**Admin attempt:** existing signed-in Browser Use task, blank hint and
exact Littleport listing only, duplicate check already passed. Browser Use
returned insufficient_credits before beginning the run. No registration
receipt, submission, stage, source activation, or publication. Do not
retry that blocked tool or use SQL/direct API as substitute. When normal
authenticated Admin access is available, submit precisely the Littleport
listing (blank hint) via Preview/Confirm and check receipt/registered
source/full snapshot/eligible public events. Native WordPress API
recognition and normalized positive read are not an Admin receipt.

**Existing native TEC path improved** (not a parallel collector):
`wordpress_adapter.collect` validates publisher-declared body
`total` and `total_pages` on the canonical registration-derived
source key only, before filtering. Enforce consistent declared counts
across pages, count raw rows, preserve recurring distinct start identities,
reject repeated raw members, empty intermediate/contradictory terminal
pages and existing >5-page cap. Explicit 0/0 and 0/1 empty conventions
accepted. Old bodies missing declared counts on first response retain
existing compatibility; legacy reviewed/Mapsee source-specific paths
unchanged. No new network calls or shared file edits. Custom WP still
needs shared owner support for actual response headers and source-bound
continuation; no invented checkpoint admission.

**Evidence:** 11/11 new unittest cases passed on exact GitHub blobs in a
short-lived Vercel sandbox, using actual updated collector, actual
mapsee_adapter.parse_tribe, reviewed venue addresses and worker factual
normalization functions AST-isolated from unrelated worker imports.
Unrelated source-specific dispatch branches used fail-on-invocation
sentinels. Real Littleport native read returned one normalized row;
native optional media capability and complete registration/DB stage/public
path were not exercised. Earlier shadow sandbox expired before replay,
so used one fresh bounded authorized API read. Both sandboxes stopped or
expired; no routine CI, no production deployment or broad source checks.
Earlier 43 provider fixture cases remain passed for unchanged files (54
focused cases total across both runs). PR #490 stays draft for coordinated
release; shared fingerprints not modified. Future actual multi-page
publisher, durable claim continuation and Admin verification still needed.
---
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
