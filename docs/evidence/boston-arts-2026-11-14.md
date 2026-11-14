# Boston arts, library, makers and bookshop collector evidence

Verified on 14 November 2026. These are new profiles, separate from the already published Boston sources. The feed adapters reuse native TEC, iCalendar, BiblioEvents and IndieCommerce event structures.

| Source | Captured rows | Full description length | Street addresses | Durable checkpoint |
|---|---:|---:|---:|---|
| Pao Arts Center | 4 | 2182–11899 | Complete | 4/4; 23,467 bytes |
| SoWa Boston | 1 | 427–427 | Complete | Not needed |
| Mill Forge Makerspace | 9 | 450–1813 | Complete | Not needed |
| Arts at the Armory | 55 | 62–3576 | Complete | Not needed |
| Trident Booksellers & Cafe | 40 | 267–3661 | Complete | 40/40; 70,162 bytes |
| Brookline Booksmith | 20 | 229–4274 | Complete | 22/22; 54,062 bytes |
| Harvard Book Store | 22 | 2323–7185 | Complete | 22/22; 125,734 bytes |
| Porter Square Books | 18 | 209–4145 | Complete | 19/19; 45,554 bytes |
| Boston Public Library | 306 | 113–2430 | Complete | 33/33; 446,704 bytes |

## Description and address verification

The full native detail body or feed description is preserved through the 12,000-character publication contract. Missing or oversized descriptions are held; no shortened summary is substituted. Bookshop pages are hydrated because listing summaries and JSON-LD descriptions are truncated. Native malformed JSON-LD addresses are replaced by the visible event address, including offsite Harvard and Porter venues.

Pao uses permitted public HTML because its Squarespace export URLs are disallowed by robots. Four IndieCommerce hosts advertise a 10-second crawl delay; their complete manifests and detail hydration are checkpointed. The real worker replay persists each checkpoint before staging and stages zero rows from incomplete snapshots.

BPL traverses all 33 native gateway pages before staging. Its upstream date filters do not constrain results, and ongoing exhibitions occur as late as the final pages. The exposed scope is a rolling 7-day physical program window plus ongoing multi-day events. All 306 eligible captured programs have native full descriptions, branch street addresses and actual branch coordinates. The complete checkpoint is below the existing 900,000-byte database limit.

SoWa First Friday resolves to the official artist studios visitor entrance at 450 Harrison Avenue. Armory Cafe and Performance Hall categories resolve to the official venue at 191 Highland Avenue. No viewport coordinate was substituted for a venue point. Missing coordinates remain available for normal address geocoding.

## Explicit holds

- Brookline Small Press Book Club is Zoom-only.
- Brookline Emmaia Gelman event deliberately shares the exact venue only with registered attendees; no guessed bookstore address was assigned.
- Porter Square Books November 19 story hour has an empty native detail description.
- Armory Open Mic native UID 20322 has only “Details TBA.” as its description.

## Validation

- Nine parser/checkpoint tests pass, including full descriptions beyond 2,000 characters, all-page manifests, resumed checkpoints, exact identities, forbidden URL rejection and changed pagination.
- Captured responses were replayed through the actual `_process_claimed_source_with_pacing` path with only HTTP and RPC side effects replaced. Completed outputs preserve exact descriptions and addresses.
- The adjacent JSON records exact source counts, all street addresses, checkpoint byte sizes, selected full-description SHA-256 hashes and worker replay results.

## Remaining discovered sources

The subsequent consolidated batch will assess Brookline Library and ShowUp repairs plus the official MFA, ICA, USS Constitution Museum, Boston Center for the Arts and seasonal SoWa pages. Boston Children’s Museum and Brattle calendar requests returned 403 and remain access holds. Production rollout and database validation are recorded by the batch owner.
