# Registered HTML calendar fixtures

`lansdowne/manifest.json` records the exact public URLs, guarded-fetch capture
times, original payload hashes and sizes, and hashes of the reduced test files.
The replay clock is fixed at 2026-11-22 12:00 UTC.

The reduced files preserve factual Event JSON-LD, original canonical URLs,
headings, visible event dates and Show times, complete event-link inventories,
navigation ancestors, and pagination metadata. Unrelated page prose and
nonessential attributes are removed. Publisher biographies and metadata
descriptions are replaced with **explicitly synthetic text**. Original narrative
lengths are retained as capture observations in the manifest; the fixture text
is not represented as original publisher prose. Full original captures were
used separately for guarded live replay and are not included in this repository.

These captures exposed an important scope distinction: the homepage showed
11 event links while the linked `/events` calendar showed 15. The document's
`rel=next` continued to WordPress archive URLs repeating the same event links,
while the Rockhouse widget uses a separate `rhp_paged` query contract. Review of
the referenced public frontend dependencies found search-suggestion pagination
separate from the archive, CTA decoration of existing ticket links, and no main
event-list append or infinite loader. The public asset URL, hash, capture time,
and scope observations are recorded in the manifest; third-party JavaScript is
not copied into this repository.

The complete-widget replay requires the origin `/events` path, a true archive
flag, exact canonical, one widget/generalView, desktop and mobile List modes,
empty query and inactive hidden filters/search, explicit month/year/weekday
cards, and no native pager or loader. Only that contract scopes pagination to
the event widget. Changed/missing fields, native pagination, and ordinary
generic document pagination still require a complete bounded traversal or hold.
The homepage remains an incomplete highlights page.

The detail fixtures also exercise exact JSON-LD event identity, date/time-bound
Rockhouse description containers, and native image evidence without inventing
end times or venue coordinates.

The synthetic tests in `tests/test_registered_html_calendar.py` also exercise
bounded, complete pagination; failed or repeated pages; query-scope retention;
unrendered FacetWP controls; deadlines; and ambiguous event facts.
