# Scoped HTML calendar improvements — 2026-11-23

Owner request: improve the EventQuest registration collector's manual-review cases for bounded calendar pagination and event details lacking JSON-LD. Keep one registration intake and existing publisher robots/rights controls.

## Existing evidence
Production registration cohort showed 4 `html_calendar_pagination_needed` (Madison County MyCountyParks, Cambridge Corn Exchange, Cambridge Junction, V&A) and 4 `html_calendar_event_jsonld_missing` (Farmville Chamber, Commonwealth Brewing, Waterside District, LSE). These reasons are not evidence that each publisher is safely parseable by one generic rule. Separate publisher inspection found Corn Exchange linking `?page=2` and Junction linking `/whats-on/page/2/`, with many more pages; some calendar pages use client-side pagination. These remain held when completeness cannot be proven. Farmville Chamber's publisher-owned full ICS was addressed by the earlier linked subscription discovery and is preferred over scraping detail prose.

## Change
1. Teach the existing registered HTML calendar's pagination checker to follow a **single numbered successor** only when a real navigation element declares exactly one active current page, links the numerically next page, and the link preserves all publisher-host/query/collection-scope constraints. Reuse the same `MAX_LISTING_PAGES`, `MAX_DETAILS`, full snapshot, deadline, cycle, duplicate, and missing-page checks. If a calendar needs more pages than the cap, keep it in review; never accept a prefix of pages or jump to the last link.
2. Add a strict alternative for a detail lacking Event JSON-LD **only** if its fetched HTML contains exactly one Schema.org Event microdata object with its own name, offset-aware ISO start/end, Schema.org Place/PostalAddress containing street/city/region/postcode, and a matching canonical identity. Reuse the current `mapsee_adapter.record` and native evidence validation. No NLP extraction, guessed timezones, website-wide venue defaults, client-JS rendering, or unverified event dates.
3. Add isolated regression tests for the positive complete two-page path and event microdata, as well as negative cases: unknown pagination current page, scope-changing page links, missing offset/address, multiple Event objects and unstructured event prose.

## Acceptance gates
- Run focused tests before merging. Owner disallowed **routine GitHub Actions**, but manual targeted tests are permitted by explicit request. Do not assume tests ran if no test runner is available.
- Deploy collector via its existing Vercel project only after merge review.
- Read the real production registration receipts and live worker results in Supabase; verify that each previously held source actually produced a validated complete collection and public events before marking it fixed. A new parser capability is not proof that the eight historical publisher pages now pass.
- Use supported authenticated registration recheck workflow; do not directly change review status or bypass publisher access decisions.
