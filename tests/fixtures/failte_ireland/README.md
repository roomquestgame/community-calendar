# Fáilte Ireland CSV schema fixtures

`historical-schema.csv` is derived from the official CKAN datastore response
recorded in `manifest.json`. It is **not** a fresh response from the live CSV
endpoint. All 1,589 historical rows are retained, but CKAN's datastore-only `_id`
is removed and each narrative description is replaced with synthetic multiline
text. CSV record newlines are normalized to LF. Published event names, date/time
columns, venue facts and URL fields remain useful schema evidence.

The latest end date is 18 January 2025. Current-window tests must produce zero
eligible occurrences and a registration review. Upcoming events are explicit
synthetic records in `test_failte_ireland.py`; the historical dates are never
shifted to manufacture current publisher evidence.

The manifest records the original response SHA-256, fixture SHA-256 and field
schema so the reduced fixture can be distinguished from the source capture.

## Current official CSV

`current-schema.csv` is a three-row reduction of the single successful exact
CSV request made after the quota reset on 23 November 2026. The current twenty
headers include optional `Image`; dates use strict `DD/MM/YYYY`. Two published
clock-bearing examples retain their dates, venue facts and event URLs. A third
example lacks a start time and must remain omitted. Descriptions and Image
values are explicitly synthetic, and phone fields are blanked. The fixture does
not grant image reuse or manufacture missing times.

`current-manifest.json` records the original body's hash and the reduced
fixture hash, fresh response metadata and complete-capture counts. The full
4.85 MB publisher response is intentionally not stored in this repository.
