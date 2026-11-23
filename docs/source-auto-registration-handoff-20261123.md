# Automatic registration repair handoff — 2026-11-23

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
