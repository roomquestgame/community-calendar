# New York arts, family, books and markets: reviewed remaining sources

Reviewed November 14, 2026. This batch contains nine additions and two repairs with zero public events at the production audit. Sources already working and published are excluded. The capture contains **362 complete-description rows across 11 profiles**, **16 street variants**, and **six descriptions longer than 2,000characters**. Every accepted row has a nonblank full narrative, a structured NY street address and a publisher event URL.

| Source | Borough | Captured rows | Description range | Collector |
| --- | --- | ---: | ---: | --- |
| [Children’s Museum of Manhattan](https://cmom.org) | Manhattan | 144 | 53–2259 | TEC |
| [Staten Island Children’s Museum](https://sichildrensmuseum.org) | Staten Island | 29 | 181–1634 | TEC |
| [Staten Island Museum](https://www.statenislandmuseum.org/events/) | Staten Island | 6 | 256–885 | TEC |
| [Queens County Farm Museum](https://www.queensfarm.org/events-calendar/) | Queens | 58 | 442–1486 | TEC |
| [Museum of the Moving Image](https://movingimage.org/events/) | Queens | 92 | 101–2479 | TEC |
| [Poster House](https://posterhouse.org/events/) | Manhattan | 13 | 670–2522 | TEC |
| [Materials for the Arts](https://www.materialsforthearts.org/events/) | Queens | 1 | 844–844 | TEC |
| [Lewis Latimer House](https://www.lewislatimerhouse.org/events) | Queens | 3 | 448–932 | Squarespace HTML |
| [Historic Richmond Town](https://www.historicrichmondtown.org/events) | Staten Island | 3 | 710–1043 | Squarespace HTML |
| [POWERHOUSE Arena and Columbus Circle](https://powerhousearena.com/events/) | Brooklyn / Manhattan | 4 | 1244–2498 | Events Manager HTML |
| [Grand Bazaar NYC](https://grandbazaarnyc.org/events/) | Manhattan | 9 | 411–577 | HTML with checkpoint |

## Description and address decisions

The seven TEC profiles reuse the existing parser, then restore the complete normalized publisher narrative. Missing or over 12,000-character narratives are held instead of truncated. Closed, explicitly virtual, private, members-only and undivided all-day listings are excluded. Native America/New_York timestamps must agree with publisher UTC fields. Pagination is bounded and conflicting identities fail closed.

Lewis Latimer House and Historic Richmond Town read public HTML detail bodies because Squarespace JSON/ICS exports are robots-restricted. Detail identity and schedule must match the listing. Multi-day seasonal listings without individual occurrence hours stay held. POWERHOUSE preserves separate Brooklyn and Columbus Circle addresses. Grand Bazaar uses full editorial paragraphs instead of its truncated calendar-export excerpt, with three detail requests per durable checkpoint and no partial publication.

CMOM maps only reviewed internal room identities or reviewed daily program labels to 212 West 83rd Street. Staten Island Children’s Museum preserves native coordinates and normalizes its Building M address into one structured street line. Staten Island Museum retains park-specific locations; Great Kills uses the documented park entrance while retaining the event’s complete meeting instructions. Materials for the Arts preserves its publisher venue point and floor label. Other coordinates remain unset for the existing address resolver.

## Verification and deployment boundary

The local review used captured public publisher responses and real parser outputs. All 11 robots endpoints returned 200 and allowed the production User-Agent at the exact calendar/API target. The local direct transport cannot complete its public-DNS check in this environment; this is recorded rather than bypassed. Root’s guarded production collector and publication receipt remain the end-to-end gate. The 30 current arts/nightlife tests passed; the 16 arts tests cover full bodies, blank/oversize holds, scoped address repair, schedule identity, pagination, checkpoint replay and tamper rejection.

The adjacent JSON research file contains registration tuples, publisher/address evidence URLs, held candidates and long-description SHA256 baselines. The capture JSON contains every accepted row with its full description and description hash. Counts are a dated capture, not a claim that those events have been published.

## Remaining candidates with concrete blockers

| Candidate | Remaining work |
| --- | --- |
| [Bronx Museum](https://bronxmuseum.org/events/) | Actionable next batch: custom structured date/detail adapter and closure filtering required |
| [Queens Museum](https://queensmuseum.org/calendar/) | Hold: official address lacks a numbered street; need reviewed entrance/address resolution and occurrence-specific multi-day schedule |
| [New York Transit Museum](https://www.nytransitmuseum.org/programs/) | Hold: every audited TEC description blank. Needs bounded detail hydration checkpoint and location review; generic TEC feed alone is insufficient |
| [Greenlight Bookstore](https://greenlightbookstore.com/events) | Actionable next batch: full detail hydration, bounded pagination and venue-specific location preservation needed |
| [National Lighthouse Museum](https://lighthousemuseum.org/events/) | Hold: audited feed had no still-upcoming occurrence at capture time; no dates invented |
| [Alice Austen House](https://aliceausten.org/events/) | Hold: tested event feed empty; needs active future schedule confirmation |
| [MakerSpace NYC](https://www.makerspacenyc.com/) | Discovery only: direct complete feed and occurrence locations unverified; not registered |
| [Flushing Town Hall](https://www.flushingtownhall.org/events) | Discovery only: independent complete-content and schedule adapter verification required; not registered |
| [Brooklyn Children’s Museum](https://www.brooklynkids.org/events/) | Discovery only: custom occurrence schedule adapter required; not registered |

The strongest next addition is Bronx Museum: its official calendar publishes a December 4 Winter Holiday Market and Teen Night plus December 12 Family Day at 1040 Grand Concourse. It needs a custom WordPress date/detail adapter and closure filtering. Queens Museum needs an independently resolved numbered street or reviewed entrance because its official visitor address is the park building. New York Transit Museum’s 27 audited TEC records all have blank descriptions, so a generic feed adapter would not satisfy this request.
