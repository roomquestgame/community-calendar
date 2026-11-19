# Lowcountry 20-feed rolling queue — 2026-11-19 06:40 EST

## Live evidence / current batch
- **VALIDATED — 1 new source**: `beaufort_library_st_helena_sc`, publisher Beaufort County Library St. Helena Branch, official first-party canonical ICS `https://beaufort.librarycalendar.com/events/feed/ical?branches%5B80%5D=80`.
  - The prior hold of 1,450/1,451 raw VEVENTs is resolved: publisher **supports** direct `&start=2026-11-19&end=2027-01-18` on the identical filtered ICS URL, returning HTTP 200, 63 VEVENTs / 44,931 bytes. Other attempted date/start_date/field_date_value variants returned the full 1,450 and are not supported. Rolling fetch bounds are regenerated each collection; the source registry keeps its stable canonical URL.
  - Robots permits native ICS endpoint. Original publisher event URLs such as `https://beaufort.librarycalendar.com/event/chess-club-3935` have strict exact-host event-path checks. 37 of 63 dated events pass the existing strict guarded collector: verified numbered street **6355 Jonathan Francis Sr. Rd, St. Helena Island, SC 29920**, publisher GEO **32.3879972,-80.5713595**, narrative, 60-day window, UTC DTSTART, recurrence identity and native event-specific category. Classified sample: Hang Out 15, Learn 11, Civic 6, Create 3, Gardens/Nature 1, Movies/Theater 1. No default Other, no fabricated images or coordinates. 26 other records intentionally filtered/held.
  - Collector code and focused tests in this PR. Requires independent one-forward-PG17-migration source enrollment through only protected `.github/workflows/db-deploy.yml`, plus exact-production staged/public readback. **37 are collector candidates, not claims of public cards**.
- **Already registered — exclude from NEW**: original five Hilton Head sources (21 historical published) and five Beaufort Library Hilton Head, Bluffton, Beaufort, Port Royal, Lobeco sources (239 published before this run). The ten total are already in production; do not re-enroll.

## All nine discovery lanes — follow-on source queue/holds
| Discovery lane | Original publisher leads to investigate / next technical gate | Current validated new feed count |
| --- | --- | ---: |
| Nightlife & Social | Jazz Corner ticketing event detail parser; avoid Culture HHI duplicate; Hilton Head Distillery path previously 404 | 0 |
| Arts, Culture & Education | Art League HHI `https://shop.artleaguehhi.org/module/events.htm` is live first-party ShopKeep HTML; verify dated classes / 106 Cordillo Parkway versus alternate class rooms. Coastal Discovery `https://www.coastaldiscovery.org/winter-program-schedule/` live HTML; per-event streets and dates; Arts Center theater events | 0 |
| Outdoor & Active | Coastal Discovery grounds and Sea Pines guided nature tours; verify official occurrence URL and actual excursion meeting street | 0 |
| Food & Drink | Sea Pines culinary programming and original Hilton Head restaurants; reject undated marketing pages | 0 |
| Family & Kids | Coastal Discovery family programming / St. Helena library family events are within this feed; do not double-count other category for one feed | 0 |
| Sports & Fitness | Original Sea Pines racquet/fitness schedules and Island Recreation (existing; don't duplicate) | 0 |
| Markets, Makers & Shopping | Art League class/events and direct organizer calendars for local Bluffton markets; verify first-party and street | 0 |
| Gaming & Hobbies | St. Helena's 37 included chess/Mahjong under one newly verified library feed; separate chess venue leads must have standalone first-party schedules and numbered meeting street | 0 |
| Civic, Volunteering & Community | St. Helena includes six civic events in verified feed; Hilton Head municipal calendar official robot/event-level source pending | 0 |

## Ready / held and deployment policy
- Ready validated feed **1**: `beaufort_library_st_helena_sc`; publish incrementally, do not hold to reach 20.
- Other nine-domain leads above are **unverified holds**, not valid queue entries; no source keys invented for them.
- Hold St. Gregory Parish Life Center Bluffton's unresolved exact GPS; no city center, parish office or guessed point.
- Do not change PostgreSQL 17 baseline, unrelated overlay/category reclassification jobs or existing records.
- After merge, prove collector Vercel READY exact SHA, then forward-only DB enrollment with guarded publisher/source/description checks, protected workflow, and separate actual **public scheduled** event count. Do not treat raw 63, eligible 37, or staged rows as public cards.
