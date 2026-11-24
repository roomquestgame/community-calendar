# EVE-159 — Extend source-bound fetches with publisher-verified second-phase API pages

**November 24, 2026 — additive Python-only planning; not active in the collector.**

## Problem solved

Spektrix public API collection has two dependent phases. First, within the
existing 60-day EventQuest window, fetch event and performance lists in
seven-day segments plus the public venue list. Second, use each uncancelled
on-sale performance's actual `planId` to request its seating plan. Every
plan then resolves to `venue.id` and the venue's specific address.

The earlier immutable pagination-plan core could append one HTML next link
while fetching a page, but could not add *several* evidence-derived API
requests after finishing all base pages. As a result, Spektrix could not
form one complete 60-day snapshot across worker leases.

## Changes

- `feedzilla_pagination_checkpoint.extend_verified_tasks()` accepts a
  bounded, unique list of new HTTPS requests **only after the existing
  phase's every URL has been fetched and acknowledged**. Original source,
  adapter, window, page receipts and cursor are unchanged. Terminal or
  partially fetched plans cannot be extended. Task manifest SHA-256 updates.
- `feedzilla_capture_store.add_verified_requests()` applies the same
  transformation to the compressed source-bound envelope. The storage
  remains self-contained and resumable.
- `spektrix_capture_plan.base_tasks()` produces exact seven-day v3
  `events`/`instances` and final `venues` URLs for the approved client.
- `spektrix_capture_plan.plan_tasks()` reads the **already captured**
  public event/instance responses, proves each on-sale performance refers to
  an event in that manifest, checks every plan ID and returns the corresponding
  bounded, exact client-scoped plan endpoints. It never guesses plan IDs.
- `spektrix_capture_plan.project()` rejects missing/altered base pages,
  wrong second-phase plan URLs or mismatched plan IDs before invoking the
  existing event/instance/plan/venue projector. Final publication is still
  controlled separately by the database and staging pipeline.

The `scope_verified=True` argument is a required **caller assertion**, not
self-authenticating publisher proof: the intended worker must pass only
exact URLs returned by `spektrix_capture_plan.plan_tasks()` after live
robots-aware, source-bound fetch validation. No public UI, external
registration or raw database change in this PR.

## Testing and release boundary

Exact new file blob hashes were compared with the local test files.
Five new plan/projection tests plus six dynamic-pagination tests passed.
The complete focused local suite (existing capture, pagination,
WordPress, Wix and Spektrix smoke tests included) passed **68 tests**.

**This is NOT a 60-day production ingestion.** The new source/lease-fenced
database capture RPC is in separate unmerged app draft PR #1894, and the
provider stage gate is in app draft PR #1892. A future worker must still
persist CAS checkpoints under an active source lease, resume after each
bounded chunk, prove record staging receipts, obey publisher permissions,
and integrate `fetch_pending` without borrowing OpenActive's special
continuation path. Original London #1217–1226 stay untouched.
