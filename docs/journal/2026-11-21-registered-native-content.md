# Registered native calendar content — 21 November 2026

Workstream: [EVE-150](https://linear.app/eventquest/issue/EVE-150), under EVE-79.
The source diagnosis and 11-row Suffolk review preparation are recorded in
comment `77fc50a9-62b6-4974-aa00-c56a22201041`.

## Change and review boundary

Ben's Cambridge expansion requires eligible official calendars to reach normal
private review and public Events/Map with their actual content. The direct
registered WordPress/JSON-LD path currently truncates native descriptions and
omits native image candidates. Suffolk additionally fails before staging because
its native timed records have empty venue objects.

The authorized coordinated change adds a strict backend-advertised native v1
contract. This repository owns collector extraction/evidence and media
negotiation; the app repository owns canonical registration, staging/receipt,
downgrade, protected venue/publication and media eligibility guards. Read the
[complete contract](../registered-native-content.md) before release.

The code retains all current source access, robots, fetch/pagination/time limits,
record identity, actual venue facts, source/worker failures, media probes and
leases. The five new fixed native errors join the existing closed diagnostic
vocabulary. No Requests subtype observability change is bundled here.

The WordPress-only private exception preserves blank name/address/null GEO and
does not copy a source default, infer a location or enable a source. Backend
publication remains dependent on actual protected Admin review. Root owns all
routine Admin/data changes and post-release Events/Map acceptance.

## Preparation and verification

- Read available collector `AGENTS.md` and current implementation patterns.
  `.claude/bram-conventions.md` and `app/__shell/conventions.md` were absent from
  the exact tree and exact-path history. The session owner clarified that this
  workspace has no Bram Worklist host surface; no host approval was invented,
  no instructions were edited and no actual permission gate was bypassed.
- Pinned the original collector snapshot at `ca1de7b025b776ebab3cb1e0fcd74949fe3e7395`.
  The untouched focused baseline passed 77 tests and 32 subtests.
- Refreshed collector main to `637136f98d7f112ac4dd3c1bf9dc6dbc6caadb1a` and preserved
  concurrent PR #411's full agreeing JSON-LD reference change and owner tests.
- The final focused revised suite passed 302 tests and 34 subtests. Independent
  review first passed 286 tests and found a native-only URL/identity mismatch
  against the backend. The collector now checks no fragment, explicit port,
  path whitespace/control, padded ID or residual markup before the first
  native staging batch; legacy URL behavior is unchanged. Independent amended
  review also passed all 302 tests and 34 subtests with no blocking finding.
  Exact remote-head identity remains a release gate. Initial fixture defects (a zero native ID, an
  always-present pagination continuation and an earlier existing URL guard)
  were corrected without weakening production validation.
- Root's final cross-layer review identified the backend's existing bare/`www.`
  publisher-host equivalence. The native helper now uses the same lowercase,
  single-prefix normalization; it preserves original URLs and source hashes.
  Eight focused cases cover both directions, case, unchanged proof and rejection
  of sibling/other/double-`www.` subdomains. The native module passes 118 tests.
  No legacy URL, transport or redirect rule changed.
- Backend review identified that the existing byte probe did not consult robots
  for a generic native image/CDN path. Under root's explicit scope approval,
  native probes now reuse the existing cached path-policy and pacing helpers
  inside the current host permit and eight-second budget. An uncached host can
  require one auxiliary robots lookup. Denied/unrepresentable/over-one-hour
  policy waits do not become shorter invented retries or permission to crawl;
  event facts survive without an approved image. Temporary cases retain the
  existing closed defer labels. The native/media focused run passes 179 tests
  and two subtests; no live publisher or production worker was invoked.
- Independent final review passes the complete focused suite: **325 tests and
  34 subtests** after both host-parity and native robots amendments. This
  supersedes the earlier 302-case count without changing its recorded evidence.
  Exact final remote-content verification remains a release gate.
- A controlled before/after probe against the current-main base failed all
  five richer-contract expectations before the patch and passed all five
  afterward. It verifies both full descriptions, native image candidate,
  explicit oversize failure and private blank-venue intake.
- Local replay of the already captured Suffolk API response retains 11 timed
  records, all blank/null in venue/GEO, all with native image candidates and
  470–1,059-character descriptions. Three Willow records explicitly retain
  “our Workshop Barn.” No public coordinates or schedule corrections were
  synthesized and no new publisher fetch was needed for this replay.

Tests use controlled publisher/RPC/media boundaries. They do not establish
production query latency, network recovery, media validation or public activation.
The paired backend fixture must independently cover paused/restricted/no-capability
denial, blank-name default suppression, partial override denial, complete
protected per-event review and override preservation on refresh.

## Release state

Prepared for normal PR review. No merge, collector deployment, manual job,
workflow dispatch, production SQL mutation, automatic unpause or backfill has
been performed by this change. Backend contract first, collector second, then
normal supported Admin review and actual Events/Map acceptance. Previously
accepted public events and Lion's independently observed recovery are separate
from this unreleased implementation.

Southern Maltings remains a source-bound `source_network_error` with an unknown
Requests subtype. Lion's explicit “free to join” versus incidental “feel free to
bring” evidence conflict is a separate proposed rule correction. Neither is
included in this collector patch.
