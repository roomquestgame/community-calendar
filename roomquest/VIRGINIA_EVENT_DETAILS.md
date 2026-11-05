# Virginia event descriptions and publisher facts

The Virginia HTML adapter reads the unique `div#event_description` from the
detail response it already fetched. It preserves paragraph and list boundaries,
removes hidden/navigation/promotion content, and stops at embedded page-tail
headings. A missing, empty, or duplicate narrative container produces no
description; the park address is never substituted as event prose.

The description remains capped at 12,000 characters. The former 2,000-character cap could discard late fee, audience and activity evidence. The backend retains and classifies this expanded bounded narrative. Actual narrative comes
first. A concise `Meeting Location: ...` footer preserves a meeting point such
as Terrace Gardens when it is absent from the retained narrative. Existing
verified offsite venue, street/room instructions, GPS behavior, primary schedule,
America/New_York conversion, and occurrence IDs remain in place.

## Evidence contract

The adapter does not assign categories, free/paid, or audience booleans. The
shared backend classifier interprets these bounded raw publisher facts:

| Item field | Meaning and limit |
| --- | --- |
| `publisher_categories` | Labels from the unique Event types section and official DCR type links; at most 20 labels, 100 characters each |
| `details_extractor_version` | `virginia_event_details_v1` |
| `details_evidence_url` | Canonical URL for this exact DCR event |
| `publisher_details.meeting_location` | Publisher's Program/Meeting Location, at most 400 characters |
| `publisher_details.standard_fee` | Raw “Standard parking or admission fee applies” value, at most 300 characters |
| `publisher_details.extra_fee` | Raw Extra fee value, at most 300 characters |
| `publisher_details.children_welcome` | Raw Children welcome value, at most 300 characters; explicit No is retained |
| `publisher_details.registration_required` | Raw Registration required value, at most 300 characters |
| `publisher_details.registration_urls` | At most three explicit registration/ticket HTTPS references, 500 characters each; never fetched |

Other details must have one unambiguous heading. BR-delimited prose, paragraph,
list, table, and definition-list rows retain separate field boundaries.
Missing, conflicting, or oversized facts are omitted; conditions are not
truncated into a misleading Yes/No. The raw details object is at most 3,500 UTF-8
bytes, reserving room in the backend's 4,096-byte evidence namespace for its
version and canonical URL. Registration references are dropped from the end
first if necessary to meet the byte limit. Public contact information already
within the actual narrative remains subject to the description cap.

This change adds no normal collection requests. Photo selection and its
`publisher_event_html_v2` version are unchanged. Existing preview-v3 staging and
the photo capability handshake remain unchanged; details carry their independent
per-event version. The backend validates/stores the new evidence and applies
shared categorization. Deduplication preference, source identity, demand gates,
source freshness, image verification, and manual corrections belong to their
existing paths.

## Read-only capture for existing event repair

The provider-test workflow offers two optional manual diagnostics. The original
`virginia_live` input captures the same two reviewed photo examples.
`virginia_details_live` instead captures the fixed reviewed manifest at
`tests/fixtures/virginia_state_parks/enrichment-manifest-20261105.json`.

```bash
python scripts/capture_virginia_event_html.py \
  --manifest tests/fixtures/virginia_state_parks/enrichment-manifest-20261105.json \
  --overall-timeout 1200 \
  --output-dir /tmp/virginia-event-html-audit
```

The full manifest is validated before any request. Its source keys must be
registered Virginia parks; event IDs and URLs must be unique. URLs must exactly
match the official HTTPS `/state-parks/event?id=...` form. Titles, aware schedule
timestamps, and optional baseline fingerprints are validated. Limits are 350
events, a 1 MB manifest, the existing 3 MB response cap, 60 MB of total response
HTML, and 1,200 seconds overall. Each request also has a maximum 45-second
remaining budget. The workflow has a 25-minute job timeout.

Each exact manifest URL goes through the existing production publisher
transport once, retaining robots, DNS, redirect, publisher pacing, and body
guards. The diagnostic does not crawl listings, fetch photos/registration links,
access a database, or create demand. A transport denial, outage, or policy
failure stops further requests without another client or fallback. Individual
parse failures retain evidence and do not claim a successful record.

The artifact contains an incrementally checkpointed `audit.json`, full HTML
compressed under `raw/`, and a compressed main-content fragment for review.
Both full responses and fragments have byte counts and SHA-256 digests. Each
parsed record is compared with the manifest's exact event URL, provider ID,
title, start, and end. Changed facts, parse failures, and records outside the
normal discovery window are explicit. Successful capture is evidence collection,
not authorization to apply mismatching records. The companion backend repair
must independently verify the current row fingerprint and eligibility before
updating existing records. Source collection/publication clocks are not renewed
by this diagnostic.

## Validation

The focused offline suites are:

```bash
python -m pytest tests/test_virginia_event_details.py \
  tests/test_virginia_state_parks_html.py tests/test_virginia_offsite_addresses.py \
  tests/test_virginia_relative_event_links.py tests/test_virginia_html_audit.py -q
```

The real Archery Club and Widewater volunteer HTML fixtures retain their existing
capture hashes and provenance. Synthetic variations exercise paragraph/list
rendering, explicit negative audience/fee facts, unsafe/ambiguous links, metadata
limits, and changed schedule/identity handling. Transport and database calls are
mocked; passing these tests does not claim a new live publisher capture or a
production repair.
