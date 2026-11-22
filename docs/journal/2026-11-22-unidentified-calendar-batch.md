# Automatic registration for nine reviewed calendars

This batch addresses nine existing `no_reusable_calendar` receipts through the
normal URL-only registration and recurring HTML collection paths. Ben submits
the original-receipt CSV rechecks after this collector release and main
[PR1645](https://github.com/roomquestgame/RoomQuestGame/pull/1645) are verified
live. A merged adapter is not a recovered or published source.

| Original ID | Publisher | Reviewed path | Captured normalized occurrences |
| --- | --- | --- | ---: |
| 198 | Mythic Hall | Public linked Wix event cards; original `/games` URL | 14 |
| 209 | Old City Cemetery | Explicit December schedule and ceremony | 30 |
| 213 | Forest Farmers Market | Explicit Wix market dates, not general weekly wording | 2 |
| 227 | Liberty University | Current public Next bootstrap and bounded published API | 22 |
| 330 | Cambridge Past, Present & Future | Public WordPress/Eventin HTML | 46 |
| 332 | Cambridge Wine Academy | ProcessWire listing and linked details | 3 |
| 333 | The Box Room | Wix listing and exact linked DesignMyNight venue details | 30 |
| 337 | Milton Country Park | Explicit timed Wix event cards | 5 |
| 440 | Algonquin Arts | Original homepage's actual `/calendar.php` link and dated details | 17 |

Counts are extraction evidence from November 22 captures, not new unique events
or published inventory. IDs and submitted URLs remain unchanged. Algonquin keeps
its original homepage receipt while the supported discovery path records its
verified calendar endpoint. Stored legacy hints do not prevent the reviewed HTML
fallback. All accepted records carry explicit local timezone and street address;
no coordinates are fabricated.

Liberty's first HTML fetch and every referenced script use only
`events.liberty.edu` and prohibit redirects. Two specialized bootstrap getters
and the single published-events API query retain separate exact-host guards,
robots, DNS/SSRF, deadlines, pacing and request limits. The anonymous token is
transient and is not stored in snapshots, logs or event records. Fifty-nine
unresolved venue occurrences and one contradictory event time are held.

Box Room's cross-host detail allowance applies only to its exact registered
listing and the actually linked reviewed venue prefix. Two contradictory One
Piece end times are held. Undated extra sessions are not generated. UK records
preserve `Europe/London` and publisher address/country evidence; the existing
country-aware queue/geocoder integration still needs follow-up before UK
publication can be accepted. External entitlement was not verified.

## Six receipts remain outside the CSV batches

- **131 Stand Up NY / 327 Anodyne:** the embedded VenuePilot host disallows all
  crawling; no API fetch or access bypass.
- **230 City of Lynchburg:** the linked CivicEngage calendar export module is
  disallowed by robots; no path-case workaround.
- **231 Lynchburg Parks:** the public page works after its 600-second crawl
  delay. Durable pacing/resumption and a supported adapter remain internal work.
- **439 Perkins:** linked Canvas robots returns an HTML application shell. The
  shared robots reader now refuses such malformed successful responses without
  caching permission. No Canvas events fetch was attempted.
- **445 Hampton:** native NPS Mansion Tour coverage already exists. Reconcile
  original-receipt routing and missing holiday coverage without a parallel
  duplicate HTML source; see the dedicated Hampton evidence document.

The Cemetery's prior robots 403 was rechecked: current robots and public HTML
returned 200 with the calendar path permitted. Runtime access restrictions still
govern every subsequent request.

## Verification and acceptance boundary

The local focused suite passed **460 tests**, covering all nine adapters, normal registration, recurring
Liberty dispatch, shared robots cache/policy/checkpoints, exact URL/source gates,
date/time/address conflicts, privacy, bounded extraction and access denials.
Independent reviews cover the US schedules, UK adapters, Liberty transport and
final shared wiring. Main PR1645 separately exercises 197 disposable PostgreSQL
assertions for the exact reviewed-URL contract and refusal on predecessor drift.

Admin CSV support is already deployed through main
[PR1640](https://github.com/roomquestgame/RoomQuestGame/pull/1640), using exactly
`registration_id,url,note` and the existing authenticated recheck RPC. The live
duplicate and valid preview paths were inspected without clicking Queue.

No live receipt recheck, registration status edit, approval, publication, job or
refresh change is part of this commit. The 96-hour refresh, paused jobs 44/59,
source approval, rights, auth, cooldown, leases and audit safeguards remain in
force. After Ben submits, verify original receipt outcomes, approval, collection,
staging, geocoding, publication and representative Events/Map details before
changing any status to recovered. Exact release/deployment receipts are recorded
in the main repository's recovery checkpoint.
