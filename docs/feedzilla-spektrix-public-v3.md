# EVE-159 — Spektrix public v3 collector foundation (November 24, 2026)

Status: Python core + offline regression fixtures only. **NOT source admission,
a connected production collector, a 60-day checkpoint implementation or proof
of any EventQuest publication.**

## Official public API contract verified

- \`GET https://system.spektrix.com/{client}/api/v3/events?instanceStart_from=YYYY-MM-DD&instanceStart_to=YYYY-MM-DD\`
- \`GET https://system.spektrix.com/{client}/api/v3/instances?startFrom=YYYY-MM-DD&startTo=YYYY-MM-DD\`
- \`GET https://system.spektrix.com/{client}/api/v3/plans/{planId}\`
- \`GET https://system.spektrix.com/{client}/api/v3/venues\`

Anonymous, read-only GETs were confirmed through the published Spektrix API and
five individually validated client profiles. Request windows cover **at most
60 inclusive days**. Each query is scoped to 7 days inside that horizon;
no historical/undated request is allowed by the API helper. Production
registration and transport must use existing publisher access/robots,
rights and per-host pacing checks. This package does not implement its own
raw HTTP client.

A Spektrix **Event** is a production title, while an **Instance** is a
specific performance, with \`event.id\`, \`start\`, \`startUtc\`, \`cancelled\`,
\`isOnSale\` and \`planId\`. The plan points to \`venue.id\`, and the venue
endpoint supplies name and address. The client can operate several venues
and even cities. Do not copy the ticketing operator's head-office address
onto individual performances.

\`roomquest/spektrix_v3.py\`:
- Strict API/client/record identity validation; duplicate conflicts fail closed
- Stable \`client:instanceId\` identifier for each on-sale, uncancelled
  performance, never the show/event ID alone
- Local clock vs UTC verification using a configured IANA timezone and
  DST ambiguity/gap rejection
- Per-instance plan-to-venue joins; missing room/address/city fails entire
  snapshot; only evidence-backed original publisher overrides may fill
  blank venue API addresses
- Requires a real first-party event link from public Spektrix \`webUrl\` or
  a publisher-verified \`event_urls\` mapping; **never invents** a Spektrix
  booking URL when the API returns a blank \`webUrl\`
- Returns complete normalized rows for the existing EventQuest classifier/
  stage adapter to consume; contains no SQL, publication or admission calls.
- One-shot \`collect\` is a smoke/probe method only, not a production worker:
  large publisher calendars need the durable, lease-fenced checkpoint runner.

\`roomquest/spektrix_discovery.py\` recognizes a client *candidate* only
from the real publisher page's Spektrix \`/clientname/website/*.aspx\`
or explicitly linked public v3 API endpoint. It preserves the booking URL
as evidence, marks every result \`api_verified=False\`, and returns
\`ambiguous\` rather than choosing between two client names. It does not
generate API calls or accept a ticketing link as registration permission.

## Validated accounts and overlapping sources (discovery seeds, NOT code defaults)

| Spektrix client | Publisher / market | Existing EventQuest |
| --- | --- | --- |
| \`cambridgelive\` | Cambridge Live / Corn Exchange, UK | Active HTML #6359, 23 current published events — dedup/migrate only after shadow verification |
| \`adctheatre\` | ADC Theatre, Cambridge, UK | Camdram venue ICS #6130 paused on venue-location/rights review, 33 staged / 0 public — never auto-enable |
| \`thealbany\` | The Albany, Deptford, London, UK | Original registration #1226 on review |
| \`richmix\` | Rich Mix, London, UK | Original registration #1221 deferred |
| \`bristololdvic\` | Bristol Old Vic, Bristol, UK | Newly validated candidate, no matched existing registered source |

Live examples: the Albany 7 \`venues\` incl. Deptford Lounge and
Canada Water Theatre, while Rich Mix's main venue address was empty in
the public API. The latter needs a publisher-verified override, not a
guess or auto-geocoding. Venue ID values are tenant-scoped: never assume
a plan or venue ID identifies the same place across two different
Spektrix clients.

**Important pending integration before moving existing sources:**
1. Implement **reusable, durable** scheduled fetch checkpoints with
   source/lease CAS and complete-snapshot proof; the one-shot 7-day
   windows alone are insufficient for a large production source.
2. Source/host/API evidence and per-venue plan-to-address map from an
   authenticated Admin registration profile; **no direct SQL seed**.
3. Craft/Wix/HTML site event-page join for Spektrix API events with
   blank \`webUrl\`. A matching title without unambiguous performance
   identity is insufficient to invent a deep link.
4. Run shadow comparisons against the existing source history and
   cross-collector event deduplication; promote only after verifying
   venue resolution and public-card continuity.
5. Preserve the ten original London registration IDs (#1217–1226).
   **Do not requeue** them until the owner's full pagination, custom
   WordPress, Wix, and Spektrix improvements are deployed.

## Vendor references

- https://integrate.spektrix.com/docs/apieventfiltering
- https://integrate.spektrix.com/docs/api/agent-guide
- https://support.spektrix.com/hc/en-us/articles/227094568-Venues
- https://support.spektrix.com/hc/en-us/articles/11101569928093-How-to-Set-Up-Instances

## Reusable pagination checkpoint core in this batch

\`roomquest/feedzilla_pagination_checkpoint.py\` defines a source-bound,
monotone fetch progress envelope intended for Spektrix, Wix and WordPress
workers. It stores exact task URLs, a task-plan SHA-256, contiguous per-page
response hashes, immutable publisher/source/adapter/60-day-window identity,
a four-hour expiry and an explicit last-page proof. A failed/incomplete task
may retain progress, but \`complete()\` is **never** true merely because a
partial prefix is available. An observed publisher next-page URL must first
pass a provider-specific scope check before it can be appended.

This is **Python state validation only**. The existing
\`community_collector_read_fetch_checkpoint\`/
\`community_collector_write_fetch_checkpoint\` database contracts currently
authorize a narrower reviewed-source set. Spektrix, Wix and custom WordPress
are **not enrolled** by this PR. Integration must extend the private
source-profile, lease/CAS and staged acknowledgement contracts through a
focused migration, rather than adding more entries to the pre-existing large
hardcoded \`fetch_checkpoint_profile\` SQL function. No new SQL file is in
this PR.


## Craft / CMS to Spektrix event URL matching

`roomquest/spektrix_cms_links.py` is a source-independent identity join for
the common case where Spektrix's public `Event.webUrl` is blank, but a venue
such as The Albany provides an official Craft CMS event page.

It accepts **already observed, first-party** CMS page records containing the
exact event title, full HTTPS canonical URL, and one or more explicitly
timezone-aware start instants. Spektrix `project(..., cms_pages=...)` and
the bounded `collect(..., cms_pages=...)` probe can use those records for
an otherwise blank API `webUrl`; conflicts with preverified Admin links
are rejected rather than overwritten. This is a data-projection option, **not**
a Craft CMS fetcher or publication path. It matches a Spektrix event only when its title
and at least one uncancelled, public performance's startUtc agree. It returns
`{spektrix_event_id: canonical_publisher_page_url}` for a unique match.
Two pages matching a show, one page matching two shows, conflicting public
page facts, foreign hosts and naive timestamps fail closed or remain unresolved.
It does not fetch Craft GraphQL or create any source and does not infer links
from titles alone.

**Unfinished:** source-specific Craft entry/instance discovery, durable
fetch/pagination in the existing DB worker, the public record normalization
and formal cross-source deduplication/transition. Synthetic tests for the
unique match and all conflict/absence cases live in
`tests/test_spektrix_cms_links.py`. The existence of this parser is not
a functioning Craft collector or an authorized London source import.

