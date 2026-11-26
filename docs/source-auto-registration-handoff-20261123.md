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

## November 25 — supported-provider URL routing repair

Owner requested simple URL submission into existing supported collectors.
Tickera/Event Discovery now follow one advertised same-host calendar at common
calendar paths (`events`, `shows`, `whats-on`, etc.), retaining query selectors
and refusing ambiguous or venue-path-widening navigation. Their actual
collector validates the destination before registration. Provider navigation
and native Squarespace collections take priority over page SEO JSON-LD;
verified TEC/GrowthZone native discovery also precedes JSON-LD acceptance.
No new provider types, queue, scheduler, database schema or source resets.

Valid empty Tickera/Event Discovery arrays return empty recurring snapshots;
initial registration still requires extracted events. Malformed Event Discovery
rows with no valid events remain an error. Tickera's documented calendar may
be category-filtered: it represents that configured calendar, not an assumed
publisher-wide archive. Official references:
https://tickera.com/tickera-documentation/event-calendar/
https://info.ticketweb.com/client-website-services/
https://commerce-apis.squarespace.com/view-json-data

Focused URL-to-registration-to-preview and affected provider suites: 120 passed.
Existing outdated TEC reason assertions and GrowthZone registration-probe mock
signature/retry expectations were aligned with already-deployed behavior.
Read-only live state: Motorco #6403 has 11 included staged events; Knitting
Factory #6402 has 15 held for coordinates across four venue-label variants.
Both are approved/healthy/preview-complete and publication-supported. Neither
had a publication request or future public events at this observation.
Local publisher checks could not resolve DNS; this is not publisher rejection.
Required .claude/bram-conventions.md remains unavailable (404). No routine CI.
Release and live acceptance evidence will be recorded in the canonical master.

## November 26 — Event Discovery standard calendar and trustworthy recognition

Continuing broader Feedzilla; Spektrix venue-location holds remain owned by the
separate EVE-174 workstream. Current main at investigation: 67d000ed. Required
`.claude/bram-conventions.md` still returns 404; current AGENTS.md and owner scope
were reviewed. No approved HTML source is an unfinished registration queue.

TicketWeb documents native WordPress Event Discovery with distinct List,
Calendar and Artist views (https://info.ticketweb.com/wordpress-plugin/ and
https://info.ticketweb.com/client-website-services/). Live publisher evidence:
Santos advertises `get_events_for_calendar`, type `calendar`, with exact dialog
fragments bound by event ID to same-response `.tw-name` canonical title links.
The existing collector supported only `get_events_artist_calendar`.

This change admits the evidenced standard action through the existing bounded
form validator and public publisher transport, resolves exact dialog identities,
and preserves canonical URL + original sortkey occurrence IDs. Unknown actions,
mixed action contracts, mismatched dialog titles and incomplete snapshots remain
held. Event Discovery's bundled `eventon_details_shading_bot` CSS no longer
counts as the actual EventON plugin. Real EventON plugin assets/ajde_evcal remain
recognized. No other provider collector, shared worker/claim, queue, schema,
publication or refresh policy changes.

Focused four-suite verification: 70 passed. Replay of the actual Santos public
response: 8 rows, complete, America/Chicago, canonical event links, image URLs,
missing venue evidence retained. Actual Birdland artist response contains 102
cards with additional performance links; accepting only its first URL would
misrepresent completeness. Added a completeness guard; actual replay marks the
snapshot incomplete (47 single-link cards remain but must not stage). Its
calendar also declares America/Denver despite New York venue evidence; do not
invent a replacement timezone or claim publication acceptance.

Original #761 rechecked through signed-in Admin against deployed #564: parent
now links canonical Tockify child #1562, which is disabled/robots_denied. No
source was created and no alternate endpoint is authorized. Original #1298
followed deployed calendar navigation to child #1563/source #6456, collected
148 under the predecessor; new completeness finding requires correction before
acceptance. #1334's deployed navigation recheck retained the stale FullCalendar
hold because the standard action was unsupported. Recheck only after this
release. Live production acceptance and exact deployed SHA remain to be added.

### November 26 — production readback and specific-plugin precedence

#580 deployed READY as `8a66e72fe9201c2468cdcea6dfb460f9bea23891`,
`dpl_4e8S9kf3e6wyPLt5RVSdi7wff576`, canonical production alias present,
no alias error. Original Santos #1334 rechecked only after release; child #1564
registered native Event Discovery source #6458. Actual ordinary preview completed
8 future events; 0 located/public at initial read. Publisher Contact advertises
1135 Decatur St., New Orleans, LA 70122; no guessed coordinates/default applied.
Birdland #6456 paused through supported Admin after its partial artist inventory
and conflicting publisher timezone were verified; original IDs/stages retained,
0 public events. It cannot be counted as accepted native collection.

Motorco #6403 and Knitting Factory #6402 now have 11 and 15 upcoming scheduled,
non-hidden, located attributed public rows respectively. Their old staged venue
hold reasons do not override actual public membership. Both last successful
collections remain November 25; no new 96-hour scheduled refresh is claimed.
Original Tockify #761/child #1562 remains a genuine robots denial.

A final precedence check found Bourbon #1289's installed Event Discovery plugin
was being described only as linked TicketWeb inventory. Actual script/link
plugin assets now precede the ticket URLs they render, without admitting a feed;
serialized asset text does not establish installation. Full native collection
still must succeed. Four-suite verification: 71 passed. No shared schema/worker
or Spektrix changes. The remaining Event Discovery list-view contract and grouped
artist/timezone evidence require reusable implementation, not a publisher HTML
fallback or a forced publication.
