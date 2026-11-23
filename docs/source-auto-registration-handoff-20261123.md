## 2026-11-23 — Review-hold batch of 10 and reusable GrowthZone intake detector

Owner approved investigating ten of the existing feed-registration review holds while improving the registration automation, rather than bulk resetting all 73 eligible receipts. Original IDs **77, 79, 91, 129, 226, 328, 331, 441, 561, 878** remain unchanged in production. The linked ten-source audit and **source-status distinction** are in [the batch journal](journal/2026-11-23-held-registration-batch01.md).

The collector change recognizes a native GrowthZone candidate only from a real unfiltered publisher Events Calendar with two distinct same-host detail links, then uses the existing native XML adapter and its configured source-specific timezone to verify complete importability. Missing profile, invalid XML and disallowed publisher requests retain the review hold. It is **not** permission to register generic HTML or guess publisher metadata.

Important dedupe lessons: #561 has a malformed long ICS encoding but the correct Las Vegas Library calendar is **already approved at source #3228**; #878's single article is superseded by an approved collecting official full-content publisher feed **#6212**. Neither should be re-registered or blindly rechecked. The other source-specific holds require complete bounded collection evidence and venue scope validation.

**Prepared only:** a code branch, focused tests and evidence journal. Local tests and browser/collector acceptance have not run, and there is no PR merge, production deployment, Admin recheck, new source approval or newly published event receipt. A signed-in EventQuest Admin browser context is needed to submit future review-approved recheck CSVs. Maintain the owner's no-routine-CI policy.

# Automatic registration repair handoff — 2026-11-23

## UK packed LOCATION address follow-up

The normal PHCL acceptance preview exposed a separate address-contract gap:
47 exact default venue matches had verified points but no separate street
address because the registered-iCal extractor recognized US formats only.
The bounded UK extension preserves native venue names and all existing review
and point gates. It requires an explicit UK country, full postcode, a unique
numbered street and locality; it infers no coordinates or postal town.

The exact 50-event fixture and existing US/equal-end checks pass: 61 tests.
The new output adds 49 native address fields, keeps the 47 exact default bindings,
leaves the film URL untouched, and changes no other emitted fact or occurrence
identity. Seven manual timing Holds remain Admin decisions. The two chess venue
reviews may require a normal re-save after their native address is populated.
See the [address journal](journal/2026-11-23-uk-ical-location-addresses.md).

This branch is reconciled with current main
`e3ad75cfcc32ad416bea2d5047e1d5e0bf359666`, retaining deployed PR #451 merge
`2e8930101da138a44ad5ff6ef8fa840eed3571bf`. Parent-controlled PR/deployment and
ordinary source/public acceptance remain pending for this follow-up. The app's
reviewed-geocode classification fix is already deployed via
[PR #1753](https://github.com/roomquestgame/RoomQuestGame/pull/1753).

## Collector change ready for review

Branch: `fix/uk-venue-auto-registration-20261123`, updated onto main `6f1b4fc`
for PR #451; initial implementation base was `054e161`.
The only production-code change is seven lines in
`roomquest/preview_worker.py::_preview`: an equal aware start/end instant emits
`ends_at = null`. It does not fabricate a finish or make a publication decision.
Native PHCL/RHTS fixtures and 23 focused regression cases accompany the change.

The deployed community publisher already stores missing/non-positive ends as
`ends_at = null`, `end_time_verified = false`; its timed-event expiry fallback
is start plus three hours. This collector adjustment aligns staging and review
with that established contract. It requires no coordinated backend timing
migration. The independent staged-geocoder/base-Hold repair is owned in the
application repository and must be reviewed on its own merits.

Full reasoning, call paths, native URLs and verification are in
[the journal](journal/2026-11-23-zero-duration-calendar-ends.md).

## Existing release integration

Checked-in configuration identifies the Git-connected **Vercel** project
`roomquest-community-collector` in team `room-quest-game`, with production alias
<https://roomquest-community-collector.vercel.app>. There is no Render service
configuration in this checkout. `vercel.json` uses
`node scripts/vercel-ignore.mjs collector`; the runtime change qualifies for a
main-branch build, while previews and documentation/test-only changes are
skipped. The normal release is PR → merge to main → verify a Vercel READY
deployment at the merged SHA. Follow the existing
[build controls](vercel-build-cost-controls.md): no routine CI label or workflow
dispatch. These are repository integration facts, not a fresh live deployment
receipt.

## Review and deployment checks

1. Review the seven-line normalization and native-fixture tests. Positive
   durations, DST folds, all-day records, cancellations, recurrence identity,
   source identity, and publisher access constraints retain existing behavior.
2. Run the documented local focused suite. After the main updates, the current
   result including the three updated adapter suites is 437 passed plus 22
   passing subtests and one unchanged baseline test mismatch: the Tribe
   timezone table has eight reviewed entries, while its test still expects
   seven. All 23 new zero-end cases pass; `git diff --check` is clean.
3. After the parent-controlled release, use normal Admin collection for the
   exact registered PHCL and RHTS feeds. Do not manually update production
   event times through SQL or create a replacement source.
4. Reassess the latest staged occurrence before a venue review or Include.
   End normalization can invalidate a prior venue-review fingerprint because
   that identity includes the end. Manual Holds remain independent decisions.
5. Verify ends are null/unverified for PHCL stages 416610, 416626 and 416644,
   and RHTS stage 416587 (or their current same-occurrence successors). A
   future public event can show its start alone; the expiry window is not a
   displayed finish. Keep RHTS Santa aggregate 416586 held pending its separate
   session contract.

The parent approved creating a normal PR after independent review. No merge,
deployment, production write, source approval, or public acceptance claim is
part of this preparation. The parent owns release and durable regional
reporting. Capability home is EVE-6; Admin findings relate to EVE-10, and local
acceptance to EVE-150/EVE-151.
