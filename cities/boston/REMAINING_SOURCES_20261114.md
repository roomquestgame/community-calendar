# Boston remaining sources — November 14, 2026

## Reviewed second release batch

This batch contains **11 new feeds and two empty registered-source repairs**.
It excludes already working production registrations. The first Boston cohort is
tracked in [the first ledger](SOURCES_CHECKLIST.md); the four bookstore sources
that production rejected with HTTP 403 remain paused and are not retried here.

The **1,054 captured occurrences** have complete native narratives and **83
distinct source/venue/street tuples**. These are captured expectations, not live
publication counts. All profiles use exact identities, America/New_York, the
existing guarded HTML category worker and normal publication/geocoding paths.
Nine use complete-only durable checkpoints. The matching application migration
is `20261114234341_boston_remaining_source_expansion.sql`.

| Publisher | Official calendar | Change | Captured occurrences |
| --- | --- | --- | ---: |
| Museum of Fine Arts, Boston | [https://www.mfa.org/programs](https://www.mfa.org/programs) | New feed | 317 |
| Institute of Contemporary Art/Boston | [https://www.icaboston.org/calendar/](https://www.icaboston.org/calendar/) | New feed | 48 |
| Boston Center for the Arts | [https://bostonarts.org/experiences/](https://bostonarts.org/experiences/) | New feed | 4 |
| SoWa Christmas Market | [https://www.sowaboston.com/sowa-christmas-market/](https://www.sowaboston.com/sowa-christmas-market/) | New feed | 31 |
| Public Library of Brookline | [https://brooklinelibrary.libcal.com/ical_subscribe.php?cid=20102](https://brooklinelibrary.libcal.com/ical_subscribe.php?cid=20102) | Repair empty registered feed | 189 |
| Eataly Boston Classes & Events | [https://www.eataly.com/c/classes-boston](https://www.eataly.com/c/classes-boston) | New feed | 76 |
| Trillium Brewing | [https://trilliumbrewing.com/pages/event-calendar](https://trilliumbrewing.com/pages/event-calendar) | New feed | 34 |
| Night Shift Brewing | [https://nightshiftbrewing.com/events/](https://nightshiftbrewing.com/events/) | New feed | 9 |
| Waverley Oaks Park | [https://waverleyoakspark.com/events](https://waverleyoakspark.com/events) | New feed | 46 |
| Boston College Public Events | [https://events.bc.edu](https://events.bc.edu) | Repair empty registered feed | 76 |
| Rose Kennedy Greenway | [https://www.rosekennedygreenway.org/calendar/](https://www.rosekennedygreenway.org/calendar/) | New feed | 70 |
| Mass Audubon Boston Nature Center | [https://www.massaudubon.org/programs/boston-nature-center](https://www.massaudubon.org/programs/boston-nature-center) | New feed | 21 |
| Boston Cares — next 14 days | [https://www.bostoncares.org/calendar](https://www.bostoncares.org/calendar) | New feed | 133 |

## Deliberate coverage boundaries

- MFA enumerates all twenty native listing pages and hydrates every in-window
  occurrence. Only its exact source receives the required 500-candidate and
  500-event checkpoint allowance; the 900,000-byte and four-hour bounds stay in
  place. Its full captured checkpoint is approximately 404 KB.
- ICA uses native ICS date evidence with full detail HTML narratives. Boston
  Center for the Arts retains the publisher's ten-second crawl delay and holds
  untimed series headers.
- SoWa Christmas Market is a separate explicitly dated 2026 seasonal schedule,
  including month-specific hours and holiday exceptions. The First Friday feed
  remains unchanged. No 2027 recurrence is invented.
- Brookline Library retains all full native ICS narratives and resolves each
  actual branch or offsite venue. Four genuinely blank native descriptions are
  held after detail-page verification.
- Boston Cares reads its one anonymous public calendar display operation for
  fourteen inclusive calendar days. The worker permits only the exact endpoint,
  fixed calendar block and date fields; no registration/account operation or
  arbitrary POST is exposed. Open physical local shifts require a full body and
  event-specific street.
- Night Shift's explicitly published weekly trivia and run-club rules are
  expanded for 28 days. Unknown ends remain unknown, closures are respected,
  and the contradictory Nerd Night listing is held.
- Eataly reads both native Boston catalogs, complete product descriptions and
  typed UTC facts corroborated by the organizer's independent Eventbrite
  schedule. The visible UTC-as-local renderer discrepancy is documented.
- Waverley Oaks Park supplies the venue operator's dated calendar, including
  Mighty Squirrel activities. Trillium uses its official public widget's long
  descriptions; empty and unlocated placeholder entries are held.
- Greenway uses its allowed public month/detail pages. Its one street
  intersection is accepted only for the exact named venue and official point.
  Variable cleanup meeting points remain held. Boston Nature Center uses each
  program's actual meeting venue; contradictory or unresolved locations are held.

## Completing first-batch location holds

The production geocoder left twelve occurrences waiting at six venues across
five first-batch sources: Dorchester Brewing, Lamplighter CX, Uphams Corner Food
Forest, Hope Garden, Union Church and the MFA event in Titus Sparrow's calendar.
The matching collector adds only exact reviewed venue points from the publishers
or their official partners, with MassGIS corroboration for MFA. Event identity,
description, clock and valid native street remain unchanged. The forward
migration requests an ordinary refresh only if these exact occurrences remain
unpublished. BPL also receives the publisher-supported chronological sort and full native pagination accounting. The address normalizer accepts its own exact South Boston/W Rutland abbreviations, fixing eleven staged publication gaps. Three exact BPL duplicate aliases remain suppressed. No completed working source is re-enrolled.

## Genuine remaining holds

The four bookstore profiles (Brookline Booksmith, Harvard Book Store, Porter
Square Books and Trident) returned `publisher_http_403` in the production guarded
transport and are paused for review. Their successful research captures do not
prove production access. No alternate host, proxy or user-agent bypass is added.

Boston Children's Museum, USS Constitution Museum and Brattle returned access
denials during this review. The Esplanade Google calendar export, Tavern of Tales
and Alpha Omega exports have robots restrictions. Roundhead presents a challenge;
JP Centre Yoga's official site is unavailable. ShowUp has no current future
occurrence and stays paused. Missing narratives, uncertain meeting destinations,
virtual/private/cancelled entries and contradictory schedules are event-level
holds, not fabricated replacements.

## Evidence and validation

- [Arts/library/seasonal capture review](../../docs/evidence/boston-arts-remaining-2026-11-14.md)
- [Food/nightlife capture review](../../docs/evidence/boston-nightlife-remaining-research-20261114.md)
- [Community/outdoors capture review](../../docs/evidence/boston-community-remaining-20261114.md)
- The application evidence directory contains the remaining-batch capture
  summary, isolated live-helper SQL preflight, production readback SQL and
  capture-to-stage-to-publication comparisons.
- The first production database release succeeded in [run 43653097823](https://github.com/roomquestgame/RoomQuestGame/actions/runs/43653097823).
  Release receipts must distinguish captured, staged, public, duplicate and
  held occurrences. No routine CI/test workflow is part of this delivery.
