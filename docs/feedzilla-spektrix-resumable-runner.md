# Feedzilla: bounded Spektrix capture runner (November 24, 2026)

This is a **dormant orchestration module**, not an active provider worker.
It reuses the merged capture envelope, exact 60-day seven-day-sliced
Spektrix planner, and venue-plan projection.

- A new capture is source-bound and its inclusive 60-day window is tied to
  the original publisher-local calendar date. Each invocation checks the
  exact manifest against captured data before issuing any GET.
- The last base page and the evidenced second-phase plan URLs are committed
  in one CAS save; an empty/off-sale calendar needs no fictitious final GET.
- A resumed capture may fetch only the expected client/resource/date range
  or a plan ID evidenced by the complete base manifest. A matching host and
  checksum alone are not sufficient. Each received page is checked before
  a durable receipt is written.
- A bounded invocation takes up to eight steps and honors the caller's
  deadline/publisher budget. A stage batch is at most 20 rows and 140KB
  serialized. Atomic staging+CAS must acknowledge the exact number of
  rows and next revision. A lost reply after commit is recovered by reading
  the durable cursor; a short acknowledgement never certifies completion.
- The runner returns pending or staged only. It never invokes publication,
  registration, preview completion or a category finish RPC.

## Exact verification

Ten focused standard-library tests ran in a short-lived, network-denied
Vercel sandbox (session sbx_7i6oOR0yFhV80a8gtLyv1U4mcmpx; stopped after
testing). The six actual GitHub blobs were SHA-1 checked before Python
execution. All ten passed, including a synthetic 60-day/20-request capture
with 25 performances in two staged batches; empty window; forged same-host
client and plan; malformed page; CAS conflict; short or lost stage receipt;
expiry and deadline continuation. No publisher/DB traffic, no routine GitHub
Actions, no full repository test run. These fixtures do not verify a real
publisher or the live database transaction.

## Transport and backend checkpoint

The collector now adds an inactive `spektrix_capture_transport` binding. It
requires the exact registered source identity, collect action, category/ticket
and explicit `feedzilla_capture_version=1` claim. It binds the three exact
read/write/stage RPCs, includes the previous SHA and CAS revision for atomic
staging, uses the existing robots-aware GET with redirects disabled, and
limits only the dedicated checkpoint read to the existing 920KB ceiling.
All other RPC response ceilings are unchanged. The nine exact source blobs
were verified and **13/13 focused tests passed** in network-denied sandbox
`sbx_Cucf3SIuNTTUUDstDY9bvLyxaONw` (stopped). Three new tests cover exact RPC
scope, missing capability denial, and the scoped 849KB read using the actual
RPC function with mocked transport (not a full application import).

App draft #1894 now binds the capture to preview generation, provider profile
hash and immutable four-hour origin and includes the atomic common-stage
writer/CAS RPC and independent private member receipts. Exact SQL rollback
preflight returned seven true structure/ACL checks, with three invalid-token
denials; no genuine active-source staging was exercised. Live readback:
no tables/RPC, zero active profiles, and no Spektrix category route. Both
DB drafts must be rebased/restamped ahead of the current migration ledger.

## Release boundary

Durable publisher pacing, source-bound category claim/continuation, and an
independently verified final staged membership acknowledgement still need
implementation and a real publisher test. Ordinary fetch_pending/category claiming must
not be reused until the corresponding source-bound continuation and
publish guards exist. Keep existing providers, approval and Admin registration
unchanged. No London #1217–1226 rechecks until all four approved capabilities
have been implemented and verified. See EVE-159.
