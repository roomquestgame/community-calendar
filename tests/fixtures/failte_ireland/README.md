# Fáilte Ireland historical schema fixture

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
