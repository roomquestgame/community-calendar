# EVE-159 — Bounded durable capture envelope for Feedzilla

November 24, 2026 · Python state format and offline test fixtures.
**Not a deployed, database-backed checkpoint worker.**

## Architecture

The existing `feedzilla_pagination_checkpoint.py` records:
- Source key, exact feed URL, adapter and at-most-60-day window
- A finite list of publisher-verifiable request URLs
- Source-approved host scope
- The SHA-256 of the request plan
- One contiguous page receipt hash per fetched request
- An independently verified terminal-page marker

It is not sufficient on its own for multi-run imports because it does
not retain the public publisher responses needed to resume event extraction.

New `feedzilla_capture_store.py` wraps that state in a **bounded,
zlib-compressed and SHA-256 verified** envelope:
- Exact original public page response text and evidence URL for each
  previously fetched task, rather than only page hashes
- A four-hour source/adapter/window checkpoint TTL, inherited from
  the existing pagination core
- A maximum of 12 MB uncompressed data and 850 KB compressed envelope,
  before database persistence
- Separate `fetch`, `project`, `stage`, `done` phases: a downloaded
  page prefix is not a successful event snapshot
- A complete terminal page and 100%-acknowledged stage cursor before
  the Python readiness signal can return `true`
- Stage acknowledgements limited to 1–20 actual matching records per
  completed source-bound request, with duplicate event IDs rejected

The envelope holds only **public, already approved** publisher payloads;
this module performs no requests or event writes.

## Completion and consistency boundary

Python can prove data and cursor integrity, but it cannot prove that a
corresponding database source lease, rights approval, staging write or
publisher pacing receipt exists. The DB must independently bind and
validate all of those before saving the envelope or releasing staged
records. Merely setting `phase='done'` in a JSON payload is *not*
publication authority.

**Do not extend** the giant existing immutable `fetch_checkpoint_profile`
SQL literal with Spektrix client names. Instead implement a focused private
provider-profile lookup and a dedicated active-lease/CAS RPC for this
envelope. Source records must still come from authenticated Feedzilla Admin,
and source conversion must reconcile overlapping HTML/ICS events before
publishing.

The intended full end-to-end sequence is:

1. A registered, authorized provider receives a source-bound category lease
2. Normal robots-aware transport captures 2–3 validated pages per worker run
3. The worker writes the *new* compressed envelope under its lease + CAS
4. The existing scheduler resumes from the exact acknowledged cursor
5. Provider parser proves full event and venue inventory
6. Bounded native stage RPCs acknowledge each record
7. Only fully staged and completed snapshot may request publication

The current production finish RPC has special `fetch_pending` behavior for
OpenActive; Spektrix and generic HTML need their own guarded continuation
contract before activation. That database-worker linkage remains unfinished.
No London source #1217–1226 is requeued by adding this module.

`tests/test_feedzilla_capture_store.py` includes positive and negative
offline scenarios for source identity, terminal proofs, page integrity,
stage progress, expiry, corrupted Base64 and duplicate record identities.
The tests must be executed against the exact branch code before merge.
