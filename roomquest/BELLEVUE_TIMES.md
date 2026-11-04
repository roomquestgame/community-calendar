# Bellevue Times community calendar — first-page collection

## Authorized scope and coverage limitation

Ben authorized collecting the accessible **first page only** on November 4,
2026. This mode covers at most the **first 30 upcoming publisher cards**. The
captured first page reported **61 upcoming entries across three pages**; page 2
and page 3 returned **HTTP 403 / Cloudflare validation**, which Ben also observed.
Those later pages are outside collection scope. Their access restriction limits
coverage and does not prevent approved demand collection of the first page.

The adapter makes one request to the registered calendar URL. It never requests
page 2, page 3, or event detail pages. A successful collection means the first
page was completely validated; it does not mean the complete calendar was read.
Missing or invalid cards within that page, first-page HTTP errors, and expired
request deadlines still fail the source. No Cloudflare challenge is bypassed,
no browser user agent is substituted, and no alternate transport is used.

**Required backend pairing:** deploy the exact-source reconciliation protection
for `bellevue_times_ne` with this collector mode. Absence from the first page
must not cancel or hide an event that moved to a later page. Existing event
expiry and freshness policies still apply. Approved collection remains driven
by real user-area demand through the existing HTML lane. Full-calendar access
is not an activation prerequisite for this limited mode. The offline tests
below are not evidence of a live pull or production publication.

**Release order:** first deploy this collector and confirm its deployment is
ready. Then deploy the companion backend change that atomically applies the
exact-source absence protection and approved, demand-only registration. Do not
approve the source against the earlier full-calendar collector or before the
backend retention guard is in place.

## Exact registration and existing pipeline

| Field | Value |
| --- | --- |
| Source key | `bellevue_times_ne` |
| Registered calendar | `https://bellevuetimes.com/events/` |
| Kind / platform adapter | `html` / `html` |
| Time zone | `America/Chicago` |
| HTTP hostname allowlist | `bellevuetimes.com` |
| Worker | Existing `POST /api/html-demand`, existing HTML demand lane |
| Collection scope | `first_page` |
| Bounds | One list page, at most 30 listed cards, at most 30 seconds |

`roomquest/bellevue_times.py` has an exact-source branch in `preview_worker`.
It does not change the MyCountyParks or Virginia State Parks dispatch, their
deadlines, registrations or parsing. There is no new route, dependency, timer,
geocoder table, or direct write to public events. The normal approved-source,
real-demand, rights, staging, address-cache and EVE7 publishing gates still
apply. The snapshot represents the validated first page only. Source
registration, coverage, exact-source absence-reconciliation protection and any
reviewed address-cache imports belong to the separate RoomQuestGame backend
change. Other sources retain their full-snapshot reconciliation behavior.

## Publisher evidence and first-page completeness

The publisher uses Bellevue Community Calendar, observed version `0.10.8`.
Server-rendered cards are selected with `main.bcc-event-list >
article.bcc-event-card`. Each card supplies its own `h2 a` occurrence link,
`.bcc-card-date`, `.bcc-card-venue`, `.bcc-card-summary`, primary category and
optional image. Cards without an image remain eligible.

The adapter verifies that the publisher marks page 1 as current. It requires
exactly `min(30, publisher_total)` complete card structures and a matching count
interval: for example, “Showing 1–30 of 61 upcoming events” must contain 30 cards.
Every occurrence link is validated before normalization. Missing, extra or
repeated cards, an unexpected page number, an invalid occurrence URL, or an
unfamiliar page structure fail the source. A truly empty result requires an
explicit verified zero count. Event-specific evidence holds are counted only
after the whole first page has been parsed.

Next-page and numbered links are never dereferenced. A missing or inaccessible
next link does not affect completeness of the first page. Publisher totals may
exceed 90, while returned candidates remain bounded to 30. Structured diagnostics
label every event with `collection_scope="first_page"`; the normalization summary
also reports `publisher_total`, `first_page_count`, `has_more`, `held`,
`duplicates`, and `records`. This distinguishes limited coverage from incomplete
network responses without changing the preview API.

The shared `fetch_publisher` retains its robots checks, crawl-delay pacing,
actual RoomQuest user agent, public-HTTPS/DNS restrictions, pinned redirect
hosts, response-size limits, encoding checks and bounded deadlines. HTTP 403
on the first-page request remains `publisher_http_403` and causes no staging call
or healthy preview. The transport is never asked to fetch later pages, event
details, images, REST posts, or arbitrary calendar URLs.

The one-page design fits the existing 30-second effective collection budget
while respecting the observed 10-second publisher crawl delay. It cannot promise
that a slow or challenged publisher will finish within that budget; those runs
fail and retain their named error.

## Dates, identities and factual fields

- The occurrence query is an explicit local wall time (`YYYYMMDDTHHMMSS`) in
  `America/Chicago`. The visible calendar date must agree. A displayed start
  clock must also agree. Ambiguous/nonexistent DST instants and contradictions
  are held; no offset or replacement time is invented.
- A date-only card may use its non-midnight occurrence timestamp as the start.
  Its end stays null. A midnight occurrence with only a date is held because it
  could represent an unspecified or all-day time. Explicitly displayed midnight
  is valid: the captured Mister Mushroom program says Nov 7 at 12:00 AM through
  Nov 24 at 11:59 PM.
- End times come only from the visible schedule. Negative/zero durations are
  held; overnight duration is never inferred from a time-only range. The common
  `retain_until_end` policy retains explicit ongoing events until their end and
  uses its existing three-hour visibility rule when no end is supplied.
- The observed Nov 4 Spanish Storytime has a specific contradiction: its card
  ends at 11 PM, while same-date summary text says 10–11 AM. This occurrence is
  held as `bellevue_times_spanish_storytime_time_conflict`. A publisher correction
  that makes these agree can pass. General prose ranges are not event dates:
  LEGO lists different Sunday/Monday sessions, Bluey lists a shorter character
  meet-and-greet inside its event, and ages are not time ranges.
- Identity is the canonical event slug plus the occurrence. `bcc_return_*`
  navigation parameters are discarded. Recurring performances keep distinct
  identities. Long slugs retain a hash of the full slug before the shared ID cap.
- Exact title/start/end/verified venue/address duplicates can collapse. The
  captured parade's missing-location `-2` card is dropped only when the located
  counterpart with matching title and occurrence is in the same snapshot. A
  missing counterpart stays held. Different places or end times do not merge.
- Descriptions retain the factual card summary, bounded to 2,000 characters.
  The existing `category` remains the primary human publisher label;
  `publisher_categories` separately preserves explicit `.bcc-terms` card badges
  in publisher order, deduplicated without case sensitivity and bounded to
  20 labels of 100 characters each. Page navigation terms are excluded. No publication date,
  RSS `pubDate`, prose date, generated blurb or invented session becomes event
  timing. Optional safe publisher-hosted image URLs are normalized candidate
  metadata only; they are not fetched by this adapter.

The adapter preserves evidence for shared classification without inventing
price, audience or holiday fields. Missing labels stay empty; venue names and
event titles do not generate labels. Both positive and negative publisher
evidence survive: for example, an audience badge can coexist with an adult-only
or paid-admission badge. The captured Gem Jam summary says “free-for-all,” and
Avenue Q's summary ends with a pay-what-you-can fragment; neither establishes
unconditional free admission. Existing `record()` and `_preview()` behavior,
occurrence IDs, schedules, venues and first-page collection bounds are unchanged.

### Image publication remains unavailable for this HTML source

The adapter may return safe image candidate metadata, but this Bellevue HTML
path does **not** publish images: public `image_url` remains null. Do not describe
those URLs as approved or persisted staged-image candidates. The legacy Udell
image-candidate updater requires enrollment in `udell_geocoder_sources`, which
the Bellevue registration does not add. Its public image trigger also requires
`provider='ical'` and `publication_mode='facts_only_udell'`, so it cannot promote
this source's HTML candidates.

The shared category publisher inherits explicit null image inserts/updates from
the event-import fast path; the HTML patch adds provider/description handling
without changing that behavior. This batch leaves existing source-rights guards
intact and adds no image-permission approval or media promotion. These conditions
are defined in RoomQuestGame migrations
`20261028130000_udell_event_photos.sql`,
`20261101014000_event_import_classification_fast_paths.sql`,
`20261102115503_category_demand_workers.sql`, and
`20261103014100_html_demand_worker_and_description.sql`.

## Reviewed location evidence

All records leave latitude and longitude **null** for the existing shared
address cache and geocoding continuation. A source coverage center is never an
event location. These exact card venue/city aliases were reviewed on November
4, 2026; substring matches, other cities and unknown venues are held.

| Exact card label | Reviewed physical address | Evidence |
| --- | --- | --- |
| Bellevue Public Library · Bellevue | 2206 Longo Drive, Suite 100, Bellevue, NE 68005 | [City library page](https://www.bellevue.net/176/Library); [City department directory, including suite](https://www.bellevue.net/m/directory/department?did=24) |
| Beardmore Event Center · Bellevue | 3750 Raynor Parkway, Bellevue, NE 68123 | [Venue contact page](https://www.beardmoreeventcenter.com/contact-us) |
| SNAP! Productions · Bellevue | 2221 Thurston Circle, Bellevue, NE 68005 | [Publisher's Avenue Q page](https://www.snapproductions.com/events/avenue-q) |
| Kroc Center · Omaha | 2825 Y Street, Omaha, NE 68107 | [Omaha Kroc Center](https://omahakroc.org/); OESC card explicitly repeats street and city |
| Bellevue Little Theatre · Bellevue | 203 West Mission Avenue, Bellevue, NE 68005 | [Official theatre](https://www.theblt.org/) |

The `Mission Ave · Bellevue` mapping is **event-specific**: only canonical slug
`nebraskas-official-veterans-day-parade`, occurrence `20261107T100000`, and its
matching title may use **209 West Mission Avenue, Bellevue, NE 68005**. This is
the parade **grandstand**, not an indoor event at an Eagles lodge and not a
default for Mission Avenue. The [Chamber event/ICS listing](https://business.bellevuenebraska.com/events/details/nebraska-s-official-veterans-day-parade-2025-2646)
identifies that grandstand address for the 2026 occurrence despite its legacy
`2025` URL slug. The [Sarpy Chamber directory](https://www.sarpychamber.org/list/member/fraternal-order-of-eagles-3912-43079515)
corroborates the ZIP code for the physical address.

A complete event-specific street address with clear location wording on a card
takes precedence over its reviewed alias. A partial street/city can complete
from the reviewed address only when both match exactly, as in the captured OESC
card. Unmatched or incomplete streets, multiple addresses, off-site locations
without an address, and contact/registration/mailing/donation address context
are held instead of falling back to the library. The old library address and
SNAP's Omaha mailing PO box are never used. OESC remains in Omaha. Location
provenance is included in the normalized record; evidence URLs are retained in
the adapter's reviewed mappings and this document.

A library card that explicitly says it meets at Bellevue Senior Center is also
held without that venue's street address, even if it never says “off-site.” The
same wording naming Bellevue Public Library still uses its reviewed address.

## Offline audit and tests

`tests/fixtures/bellevue_times_page1.html` contains only the captured list cards
and pagination from the November 4, 2026 first-page response. It deliberately
retains the reported total of 61 and the page 2 link. It represents a complete
first-page collection while explicitly showing that later entries exist.
Offline collection requests that fixture once and yields:

| First-page outcome | Count |
| --- | ---: |
| Listed cards | 30 |
| Spanish Storytime schedule hold | 1 |
| Missing-location parade duplicate | 1 |
| Distinct address-backed records | 28 |

These 28 are parser diagnostics, **not staged or published production events**.
Structured stderr diagnostics identify each held/duplicate occurrence and label
the `first_page` scope, 30 listed cards, 61 publisher entries, and `has_more=true`.
No preview API contract changes are needed. If all potentially usable entries
lack evidence, the source fails as `bellevue_times_event_evidence_unavailable`,
rather than healthy zero.

The focused suites are `tests/test_bellevue_times.py` and
`tests/test_bellevue_times_integration.py`, included explicitly in the provider
CI workflow. They cover the captured evidence, recurring IDs, date-only/midnight
rules, DST, descriptions/categories, address overrides/holds, exact registration,
first-page completeness and one-request scope, deadlines, Cloudflare-shaped
HTML, no-staging on first-page 403 or malformed cards, robots/host transport
options, and unchanged HTML-family dispatch. Synthetic pages are test fixtures
only; later live pages are neither requested nor treated as accessible.

Local validation on November 4, 2026 ran the exact provider CI pytest list:
**542 tests and 25 subtests passed** across all 23 listed test files in 2.74
seconds (3.11 seconds wall time). The optional live audit workflow was not run.

One read-only live first-page preview through the unchanged shared transport was
attempted at **2026-11-04 01:34:53 UTC**, with a wrapper allowing only one call
to the exact registered calendar URL and forbidding database RPCs. It stopped
with `dns_unavailable` before publisher HTTP. No retry, alternate fetch, later
page, staging or publication occurred. This workspace result does not establish
that the publisher's first page is blocked; live transport availability remains
to be verified from the deployed environment.
