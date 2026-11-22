# Santa Cruz Art League validation repair

Prepared November 22, 2026 against collector main
`08ff05936d36f1e56d6cff503df3b7e98479ce3d` (preserving PR #433 and PR #434).

## Confirmed cause and scoped change

Existing source **5860**, `santa_cruz_art_league_receptions_ca`, supplied its
publisher-verified address, **526 Broadway, Santa Cruz, CA 95060**. The live
`rq_curator_private.udell_address` normalizer returned NULL for that exact
suffix-free street, while the approved event URL identity check returned true.
The staging gateway therefore raised SQLSTATE 22023, “Followon10 event has no
complete narrative, original street or event identity”; the collector reported
`database_unavailable`. At the November 22 13:26 UTC readback, no staged rows or
successful preview existed. The latest recorded failed attempt was 02:18:10 UTC,
not a new attempt during this repair.

The two original owner pages and the prior verified receipt already corroborate
the street, event narrative and schedule:

- https://scal.org/first-friday
- https://scal.org/members-show-2026
- [November 19 publisher evidence](santa-cruz-ca-follow-on-20-source-discovery-20261119.md)

The separate RoomQuestGame forward migration
`20261206184400_verified_santa_cruz_art_league_street.sql` admits only that exact
verified address and preserves its original spelling. It guards the existing
function definition, preserves access/function attributes, and runs 13 positive
and near-miss assertions atomically. [RoomQuestGame PR #1667](https://github.com/roomquestgame/RoomQuestGame/pull/1667)
merged as `453edacfc4da962243636daa28c14d1c543ef635`. The guarded database
[deployment run 45029101069](https://github.com/roomquestgame/RoomQuestGame/actions/runs/45029101069)
completed successfully at **13:45:32 UTC**. Readback confirmed migration 184400 in
the live ledger, the expected function MD5 `d80ffdae83f6b4e1222c60d793e9a248`,
and **all 13 production PostgreSQL 17.11 postconditions passed at 13:46:52 UTC**.
The database dependency is ready. The subsequent collector release and canary
acceptance are recorded below. Preserve the verified street without adding a
suffix or broadening address acceptance to unrelated locations.

This collector change adds the existing
`p_parser_capability=publisher_event_candidates_v1` only to Art League's validated
success return. Its parser already attaches the matching row evidence, including
honest no-photo results. Parser identity, original HTML fetch bounds, robots,
rights, source clocks and normal staging/publication gates are unchanged. Failed
or invalid extraction and staging failures still cannot certify a snapshot.
PR #431's geocoder claim-v2 integration is retained from fresh main.

## Focused validation and release boundary

The existing completion suite now includes source 5860's real parser fixtures for
success, the historical absent-marker failure, invalid extraction and a genuine
empty result. The suite's gateway is an offline contract double, not live SQL.

- Original Art League completion cases before its marker: **2 failed, 2 passed**.
- Completion suite plus original Art League parser suite: **37 passed**.
- Independent Art League completion review: **4 passed**.
- Separate migration check: all 13 embedded assertions passed on PGlite 0.5.17
  (PostgreSQL 18.7), and a second application correctly refused the changed
  function hash. Production PostgreSQL 17.11 subsequently passed all 13 checks as recorded
  above; the offline engine result remains a separate validation receipt.

No GitHub test workflow was dispatched. The code integration itself requested no
source run. After both releases were verified ready, one authorized existing-source
Admin canary ran; its production receipt follows. The earlier Dream Inn canary is
recorded in the [six-source release receipt](santa-cruz-photo-completion-20261122.md).

## Production release and canary acceptance — November 22

[Collector PR #435](https://github.com/roomquestgame/community-calendar/pull/435)
merged as `69eed0bc1f28f28064351adaae566e9502392d0e`. The existing production
project deployed that exact SHA as `dpl_AuH71PrELFesFeDQa4NchChmVygK`, READY at
**13:53:05.935 UTC**. The canonical collector alias resolved to that deployment
and SHA at **13:54:01 UTC**. Migration 184400 was already verified live as recorded
above. PR #431 and PR #434 changes were preserved.

The one authorized **Admin Review → Queue preview** action selected existing
Art League source 5860 and its original `https://scal.org/first-friday` URL.
The click occurred at **13:56:33.524 UTC**, the database request was recorded at
**13:56:33.687584 UTC**, and the UI confirmed the request at **13:56:33.907 UTC**.
No other source was queued and source approval/rights were unchanged.

**Fresh collection and v3 completion passed.** The new stage and image observation
were recorded at **13:56:39.367908 UTC**. The accepted photo snapshot, successful
collection run and preview completion followed at **13:56:39.855809 UTC**.
The source was healthy and `complete`, with error NULL, `failure_count=0`,
and matching future/staged counts of one.

Staged event 415428 is **Simple Pleasures — Santa Cruz Art League First Friday
Reception**, December 4, 2026, **17:00–19:30 America/Los_Angeles** (December 5,
01:00–03:30 UTC), at the unchanged **526 Broadway, Santa Cruz, CA 95060**. Its event
identity remains `https://scal.org/members-show-2026`. The image candidate is
honestly NULL; `image_extractor_version=publisher_event_candidates_v1` and
`image_observed_at=last_seen_at` document fresh no-photo inspection. No old event
or image observation timestamp was reused.

**Publication is a separate pending step.** The production readback found no
public external event. At **13:58:14.514823 UTC**, normal worker eligibility was false. The included
stage had NULL coordinates and its existing publication request remained. Ordinary
area demand had expired at **02:45:24 UTC**; the Admin action supplied validation
interest through **14:26:33 UTC**, which did not make ordinary publication eligible.
The source awaits normal active demand for publication. This receipt establishes
successful collection, staging and completion; it does not establish public UI
acceptance or a geocoder outage. No manual publication or further queue action was
performed to alter that disposition.

The [redacted production evidence](evidence/santa-cruz-art-league-canary-20261122.json)
records the exact release, source, stage, completion and eligibility observations.
This receipt update changes documentation only.
