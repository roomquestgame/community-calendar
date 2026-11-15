# Boston additional nightlife — November 15, 2026 UTC

Six additional calendars are implemented using the existing Boston dispatch, guarded publisher transport, shared description cleaner and complete-only durable checkpoint path. These are parser/worker replay results, not a production release receipt.

| Source | Captured eligible occurrences | Description characters | Missing street | Missing point |
|---|---:|---:|---:|---:|
| [Lizard Lounge](https://lizardloungeclub.com/calendar/) | 30 | 332–4803 | 0 | 30 |
| [Improv Asylum](https://calendar.improvasylum.com/) | 85 | 639–2085 | 0 | 85 |
| [Laugh Boston](https://calendar.laughboston.com/) | 37 | 723–2180 | 0 | 37 |
| [Club Passim](https://www.passim.org/live-music/) | 61 | 258–7725 | 0 | 1 |
| [The Burren](https://www.burren.com/music.html) | 105 | 9–4526 | 0 | 105 |
| [Long Live Roxbury](https://www.longlivebeerworks.com/boston) | 3 | 362–362 | 0 | 3 |

The complete published native prose is preserved. Improv Asylum and Laugh Boston use their anonymous public calendar JSON descriptions because their JSON-LD previews truncate at 300 characters. Passim hydrates each unique detail once; The Burren combines complete ticket descriptions with any distinct native calendar context. Short native genre labels remain short. Long Live uses only named jazz dates and keeps holiday omissions.

One Passim event, **Tall Heights at Arrow Street Arts**, has only generic fee information on its direct page and is explicitly held. Its Ticketmaster link is `01006536E71D122A`; read-only production verification confirms it is already public with an 801-character description (public event `316b4221-4948-4240-916a-60bddc186a4a`). This direct-page hold creates no current coverage gap.

All 321 eligible captured occurrences have actual full postal streets and nonempty descriptions. Club Passim's official directions page provides an explicit marker at its 47 Palmer Street venue. The other 261 occurrences across six streets require the existing venue/geocoder path; no publisher headquarters or map viewport is substituted.

## Verification

- 28 focused tests pass: full prose, missing/over-limit narratives, exact venue binding, time-zone correction, show-vs-door clocks, closed/private events, named-date recurrence, holiday omissions, immutable checkpoints, partial staging prevention, tamper detection, safe URL scope and deadline reserve.
- Real category-worker replay of all six captured sources stages the exact same 321 complete records in chunks of at most 20. Passim takes four claims and The Burren three; every other source completes in one. There are zero partial-stage calls and exactly one publication call per source. Database writes in this replay use the existing test harness; actual live publication is not claimed.
- Native capture and expected-event hashes, exact source contracts, source notes, street evidence and held item are recorded in the companion JSON evidence. Full expected records are retained in the local replay for production comparison; the repository evidence contains their hashes.

The local guarded publisher client cannot resolve external DNS in this workspace. Existing ordinary robots-aware public captures verify parsing and event content; the normal production worker must establish production transport separately.
