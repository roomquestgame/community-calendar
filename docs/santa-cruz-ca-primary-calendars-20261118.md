# Santa Cruz, California — primary-source discovery and collector batch (2026-11-18)

This collector batch is **not** an approval to publish data or use publisher images. It adds two first-party structured WordPress/The Events Calendar REST adapters to the existing EventQuest source-preview pipeline. No old PostgreSQL 17 baseline, mobile UI, scheduled GitHub Actions, existing external_events, or source approvals are changed.

## New direct publishers and real research readback

| Publisher | Exact feed | Parser | 30-day API events returned | Full source narrative | Physical street evidence | Images | Intake |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| UC Santa Cruz | https://events.ucsc.edu/wp-json/tribe/events/v1/events | WordPress TEC REST JSON | **150** (two pages at 100/page; 2026-11-18 through 2026-12-18) | 150 nonblank raw narratives; sanitizer retains up to 12,000 characters | 107 events supply numbered streets; 43 lack usable street and are held. Campus building prefixes are removed only when a real street number is explicitly present | 143 source candidate URLs, unlicensed until backend review | Onboard adapter, hold incomplete records |
| Kuumbwa Jazz | https://www.kuumbwajazz.org/wp-json/tribe/events/v1/events | WordPress TEC REST JSON | **19** (one page) | 19 nonblank raw narratives | All 19 specify event streets; do not assume the main jazz club for offsite performances | 19 publisher candidates, subject to rights and resolution checks | Onboard adapter, await approval/geocoding |

Counts are publisher API records observed with a bounded read-only Vercel sandbox request, **not** accepted/preview-staged/published counts; future events can be excluded for cancellations, DST/time issues, missing exact venue details, invalid identities or size limits. Event field validation is stricter than the crude research counts. Publisher robots rules allowed the exact JSON routes; Kuumbwa advertises a 10-second crawl delay that production transport must obey. Pagination fails closed rather than treating an incomplete export as clean.

Santa Cruz 20-mile production discovery currently has no upcoming external event location records (read-only November 18 snapshot). Existing three Santa Cruz Public Libraries Mapsee iCalendar registrations remain enabled and approved but last showed zero future staged rows after October 28 checks; they are **not** re-registered. Existing nearby Ticketmaster, San Jose State Localist and other providers are untouched.

## Discovered but not newly enrolled

- Santa Cruz Museum of Natural History, Santa Cruz Museum of Art & History, and Bookshop Santa Cruz have official live calendars but their tested WordPress routes or robots requests returned HTTP 403 in the isolated collector test. Do not bypass protections. Investigate approved first-party JSON/ICS or site-specific access only in later batches.
- The Catalyst, Santa Cruz Beach Boardwalk, City Parks & Recreation, farmers markets, gaming communities and seasonal venues require further format, event-level address and rights validation; no speculative feeds are registered.
- UCSC event items lacking a specific numbered street and hybrid/virtual or undated listings are held, not pinned to a campus center.
- Events with unknown activity category after the shared classifier must be reviewed with title/description evidence, not assigned a fabricated activity label. File new positive/near-miss evidence in the shared category feedback system before any forward rules migration.

## Guarantees and release gates

- Source keys are exact and request URLs are restricted by the reviewed host allowlists and existing SSRF/robots protections; native EventQuest sources remain unchanged.
- Event-specific starts/ends cross-check published UTC and local time with America/Los_Angeles; only supported dated occurrences enter the common staged contract.
- Complete event HTML descriptions are sanitized, entities decoded and checked nonblank; overlong narratives are held, not truncated.
- A street number must be publisher-evidenced; city and state are accepted only from a Santa Cruz County municipality, never guessed building numbers or a default county/campus pin. Missing coords go to the existing reviewed geocoder.
- Publisher photo candidates must match exact publisher upload-host paths, avoid small/logo files, and still pass downstream byte/rights verification before display.
- No new database migration is included in this collector PR. **Next**: deploy collector through existing Vercel integration, separately stage/approve eligible source registrations in a **single** new forward migration PR, dry-run, geocode, classify, dedupe, verify and publish in normal Home/Map/Events. Do not claim visible events until read back.
