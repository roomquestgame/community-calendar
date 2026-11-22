# Automatic registration of HTML calendars with structured event details

Prepared November 22, 2026 for the FindLocal publisher-registration backlog.

## Behavior

The normal URL registration worker can accept a publisher's recurring HTML
calendar when its actual linked event pages contain usable Event JSON-LD.
Registration runs the same `registered_html_calendar.collect` extractor used by
scheduled collection before it returns a verified receipt. A calendar-shaped
URL or a list of links alone cannot register a source.

Existing ICS, WordPress, Localist, Squarespace, embedded JSON-LD, discovered-feed
and explicitly reviewed HTML adapters retain their normal priority. This is a
reusable final HTML family, with no publisher URL, address or timezone allowlist.
The submitted canonical listing remains the registered feed URL and source-key
hash input. Its event pages remain individual event identities and evidence.

The parser requires a recognizable collection heading, calendar path or
structured ItemList, and distinct same-host detail links. A single-event page,
site navigation or sidebar recommendations cannot establish a collection.
Selectors in URLs are retained. Explicit canonical links and structured event
URLs must agree with the page fetched; a trailing slash may normalize to that
actual fetched page. Local `#event` identities resolve against their own page.
Generic homepage navigation keeps all original query selectors. Venue or
department paths cannot expand to an operator-wide calendar through either
generic navigation or exploratory feed recovery; separately reviewed routes
and explicitly supplied feeds retain their existing handling.

## Complete bounded snapshots

Every selected listing page and detail must finish successfully. The adapter
never reports the first few fetched events as a completed calendar. Current
limits are three listing pages, 20 unique detail pages, 3 MB of HTML per page,
5,000 structured nodes and 500 normalized event occurrences. The existing
registration/collection deadline, robots policy, publisher pacing, public DNS
checks and transport guards apply.

The recognized Rockhouse archive List widget has a separate pagination contract.
It requires the exact unfiltered `/events` archive, its canonical URL and archive
flag, one list widget, List mode on desktop/mobile, inactive filter/search values,
and complete cards under explicit month/year headings with matching weekdays.
Any native pager or loader remains a hold. Inspection of its published frontend
dependencies established that widget paging uses `rhp_paged`, while document SEO
`/events/page/N/` links are separate; the captured document pages repeated the
same widget inventory. Only this fully matched platform contract scopes
pagination to the actual calendar widget. No publisher-specific URL allowlist,
guessed pagination request, JavaScript execution or hidden API call is added.

Observed next-page links can be followed only within the same collection path,
publisher and query scope. Cycles, repeated nonadvancing inventories, ambiguous
or unsupported controls and limits remain in review. Other explicit review
reasons identify missing event JSON-LD,
ambiguous scope, conflicting identity, unresolved timezone, invalid venue or
schedule data, detail limits and deadline exhaustion. No timezone, date,
recurrence, venue address or coordinates are inferred from the source's city.
The existing shared event normalizer owns eligibility and the date horizon.

The reviewed Forestry England Drupal venue layout uses the same negotiated
HTML/native protocol with its own complete pagination and visible-schedule
contract. It covers all discovered forest calendars, supports explicit empty
views, suppresses unlicensed image candidates and retains full native event
bodies. Its publisher-specific bounds and eligibility diagnostics are described
in [Forestry England calendars](forestry-england-calendars.md); other generic
HTML limits and recognition rules are unchanged.

## Negotiated registration and content contract

Only an exact integer `registered_html_calendar_version: 1` on the backend's
registration claim enables the new probe. A successful complete probe returns
`p_type=html` and `p_reason=registered_html_jsonld_v1`. The backend independently
requires its normal claimed registration, canonical public URL and source hash.
Recurring claims receive both integer `registered_html_calendar_version: 1` and
`registered_native_content_version: 1` only for an exact checked registered
receipt with that marker. Manually setting a source's HTML type is insufficient.

Descriptions and image candidates use the existing registered native content
protocol. The source remains `kind=html`, `platform_adapter=html`. Each record's
native proof additionally contains:

```json
{
  "evidence_url": "<the actual fetched event detail URL>",
  "extraction": "registered_html_jsonld_v1"
}
```

The structured event's description is sanitized and retained up to the existing
12,000-character bound. When that field is absent, the recognized Rockhouse
detail layout can supply its unique event description block only after the
canonical URL, event title, published date and show time agree with the Event
data. Its proof explicitly uses `description_field=rockhouse_event_description`;
the ordinary structured field retains `description_field=description`. Generic
page text and site navigation are not description sources. A larger result is
held instead of silently truncated.
An optional image comes only from that matching Event's native image field;
relative URLs resolve against the actual detail page. No generic Open Graph or
site-banner fallback is added. `image_evidence_url` and the media claim's
`extraction_url` identify that same event detail. HTML detail host matching is
exact; a different subdomain or `www` alias does not become crawl permission.

All records pass native proof validation before the first staging batch. The
existing native staging overload and `registered_native_content_v1` completion
capability remain in use. Media work stays candidate-only: the image worker
probes the staged candidate under its existing byte, MIME, redirect, robots and
pacing checks. It does not crawl the detail again. Source approval, rights,
venue resolution, curation and public Events/Map publication remain independent
backend gates.

## Release and verification

1. Deploy the reviewed collector first. The older backend omits the new
   registration capability, so this fallback remains inactive during rollout.
2. Merge the paired main-repository migration through its normal database
   deployment workflow. It enables registration negotiation and the matching
   HTML native-content contract. Its prerequisite hashes reject concurrent
   function drift; the existing exact reviewed-URL list is preserved.
3. Recheck eligible existing receipts through normal Admin controls, or let new
   automatically submitted publishers follow the ordinary registration queue.
   This migration does not insert sources, reset receipts, change source status
   or alter refresh schedules.
4. Verify the registration receipt, normal collection/staging completion,
   venue/curation outcome, optional media verification and resulting public
   Events/Map records. Parser success by itself is not public acceptance.

Focused tests cover the real registration and recurring-worker paths, native
proof and media identity, older-backend compatibility, complete-snapshot bounds,
transport denial and existing reviewed adapters. Publisher capture fixtures
record original URLs/body hashes and the deterministic reductions used in tests.
Long publisher narratives are replaced by explicitly identified synthetic text
in committed fixtures; original-response replay results are reported separately.
Recorded local test and live verification results belong in the release receipt.

