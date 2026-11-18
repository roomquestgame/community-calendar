# Hilton Head and Beaufort County SC — five official library branch feeds (Nov 18, 2026)

## Incremental primary-source audit

The earlier Hilton Head direct-source batch is already in production, with **21 published events** from its original five first-party sources. Do not duplicate those sources or events. This follow-up found the actual Beaufort County Library first-party calendar at https://beaufort.librarycalendar.com/events/upcoming (the old assumed library website /events path was 404). Publisher robots explicitly permit its branch-filtered direct ICS; none of these exact branch feeds are registered in the production EventQuest source registry.

| New source | Official physical location | Structured publisher feed (ICS) | Raw VEVENT count | Eligible 60-day dry-run |
|---|---|---|---:|---:|
| Hilton Head Branch Library | 11 Beach City Rd, Hilton Head Island, SC 29926 | https://beaufort.librarycalendar.com/events/feed/ical?branches%5B77%5D=77 | 275 | **74** |
| Bluffton Branch Library | 120 Palmetto Way, Bluffton, SC 29910 | https://beaufort.librarycalendar.com/events/feed/ical?branches%5B74%5D=74 | 158 | **49** |
| Beaufort Library | 311 Scott St, Beaufort, SC 29902 | https://beaufort.librarycalendar.com/events/feed/ical?branches%5B72%5D=72 | 241 | **44** |
| Port Royal Branch Library | 1408 Paris Ave, Port Royal, SC 29935 | https://beaufort.librarycalendar.com/events/feed/ical?branches%5B79%5D=79 | 57 | **25** |
| Lobeco Branch Library | 1862 Trask Pkwy, Lobeco, SC 29931 | https://beaufort.librarycalendar.com/events/feed/ical?branches%5B78%5D=78 | 219 | **49** |
| **Total** | Five separate libraries | Five first-party official branch feeds | **950** | **241** |

The 241 records are *isolated source collector candidates, not new public EventQuest cards*. Current publisher data may change before production preview. All 241 passed strict per-event nonempty sanitized descriptions, numbered official venue streets, publisher-native branch coordinates, canonical EventQuest category and source-specific event URL checks. Original publisher categories are retained as additional evidence; title trigger expansion handles unlabeled civic meetings, job fairs, games, writing/painting classes, book clubs, festivals, storytelling and holiday activities without assigning Other.

## Held / skipped sources and coverage limits

**St Helena Library**: publisher exact filtered first-party ICS https://beaufort.librarycalendar.com/events/feed/ical?branches%5B80%5D=80 has **1,451 VEVENTs**, exceeding safe existing raw ICS source-record limits. Do not silently truncate or register until a documented publisher-supported date-bounded endpoint or separately reviewed incremental method is implemented. The other original Hilton Head research holds remain outside this batch: Coastal Discovery Museum (unsupported TEC/ICS paths); Art League HHI (unreviewed ShopKeep class HTML); Arts Center Coastal Carolina (unverified ticketing schedule); Jazz Corner direct ticketing (not fully verified); HHI Chamber (aggregator/duplicate risk); Hilton Head Town civic calendar (robots and path unverified); Sea Pines Resort (generic HTML); Lean Ensemble (events endpoint 404); Hilton Head Distillery (events endpoint 404). Do not pad a batch to 15 by admitting unsupported feeds.

## Extraction, venue, time, image, and categorization

Only exact first-party HTTPS branch URLs are eligible. The existing publisher transport enforces robots, DNS/SSRF, redirects, allowed host and pacing. No HTML crawler is needed. Reuse existing iCalendar parser for UTC DTSTART/DTEND, proper America/New_York zone, and 60-day recurrence. Reject private/closed/undated/offsite events, wrong or blank event URLs, missing GPS, inconsistent branch addresses, missing raw description, over-12k sanitized prose, and undetermined core category. The raw VEVENT DESCRIPTION is read from the *same* publisher snapshot, not truncated at the default shared 2k field cap; HTML sanitized and entities decoded. One publisher venue exact branch street and first-party GEO per event, never a city/source centroid or inferred street number. Only title/category triggers with first-party evidence assign one of the 25 canonical EventQuest core categories; all others are held. Sample categories: Learn, Civic, Create, Hang Out, Festival, Music, Health, Gardens and Nature, Movies/Theater. Original event UID/start identity, full title, first-party event URL and recurrence remain stable.

All tested library ICS feeds contain **zero ATTACH images**. No image is fabricated. Future image candidates require official library media URL without favicon/logo/thumbnail and independent publisher rights/byte checks before actual display. Rights remain unreviewed until authorized. Preserve EventQuest's original 96-hour cache/demand refresh, native dedup and geo-category overlays without rewriting them.

## Release sequence

1. Consolidated collector PR: exact five branch URLs and safe full narrative/branch venue categories; 7 focused new unit tests plus 10 existing Hilton Head regression tests passed in isolated Vercel Linux; five-source real read-only dry run 241 candidates.
2. Collector production Vercel deployment must be READY at the exact merged SHA, no extra routine GitHub Actions CI.
3. Create **one forward-only PG17 migration in one app PR** for the five exact source configs, provenance, guarded source support/publication and geocoding, preserving the production database, all historic squashed baseline migration records, existing producers and users.
4. Deploy exclusively via protected GitHub db-deploy workflow, never direct Supabase production writes. Read back each source's actual preview/health/staged/geocoded/published event count, full text and core categories, and avoid claiming staged cards are public.
