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

## Release boundary

App drafts #1892 and #1894 remain inactive. The production RPC client
currently caps most responses at 150KB, below the 850KB capture envelope:
a dedicated read exception, not a global limit change, is needed. The DB
contract must add per-preview generation and provider-profile binding,
immutable capture origin, absolute expiration, durable publisher pacing,
atomic stage+CAS receipts, and an independently verified final staged
membership acknowledgement. Ordinary fetch_pending/category claiming must
not be reused until the corresponding source-bound continuation and
publish guards exist. Keep existing providers, approval and Admin registration
unchanged. No London #1217–1226 rechecks until all four approved capabilities
have been implemented and verified. See EVE-159.
