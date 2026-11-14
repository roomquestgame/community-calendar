# Boston nightlife, food, and gaming — November 14, 2026

## Ready for the consolidated production batch

The collector capture replay accepted **351 dated occurrences across 10 new sources**. Every accepted record passed the shared Boston street-address/description boundary and the durable checkpoint wire contract. All **351 descriptions exactly match the complete normalized native narrative**, verified with SHA-256 hashes in `boston-nightlife-20261114.json`. Nothing is shortened to the previous 2,000-character default. Narratives exceeding 12,000 characters are held rather than truncated.

This is capture and parser evidence, not a production deployment claim. The local guarded `fetch_publisher` cannot resolve DNS in this workspace; direct read-only public response captures used the environment proxy after reviewing each publisher's robots rules. Production collector code delegates every read to the existing guarded fetch transport. The batch owner must confirm that transport and compare staged/published descriptions with the supplied hashes.

| Source | Official calendar | Accepted | Held | Parsing and narrative source |
|---|---|---:|---:|---|
| Aeronaut Brewing Company | https://www.aeronautbrewing.com/visit/somerville/ | 61 | 3 | Exact JSON calendar URL embedded in official HTML; full `description`, Somerville venue slug only. |
| Notch Brighton | https://www.notchbrewing.com/brighton-events | 6 | 0 | Squarespace ordinary HTML full event-body layout. |
| Remnant Brewing & Satellite | https://www.remnantsomerville.com/live | 14 | 10 | Squarespace ordinary HTML; per-event location selects Bow Market or Satellite. |
| Castle Island Brewing | https://www.castleislandbeer.com/calendar | 11 | 8 | Squarespace ordinary HTML; distinguish South Boston and Norwood. |
| The Bebop | https://www.thebebopboston.com/new-events | 21 | 6 | Dated month list and full event detail bodies. Explicit cancellation notices excluded. |
| Lamplighter Brewing | https://lamplighterbrewing.com/collections/events | 13 | 0 | Shopify public event list and complete event product description embedded in HTML. |
| Club Café Boston | https://www.clubcafe.com/club-events/ | 12 | 0 | MEC dates paired with visible start/end clocks; full event detail narrative. Overnight end dates retained. |
| Boston Public Market | https://bostonpublicmarket.org/events/ | 39 | 0 | Sugar Calendar visible dated occurrences, hydrated from complete official detail bodies. |
| Dorchester Brewing Company | https://www.dorchesterbrewing.com/events/ | 6 | 0 | Native hCalendar clocks and full official event details, with detail/listing clock consistency. |
| Pandemonium Books & Games | https://pandemoniumbooks.com/apps/bookthatapp/calendar | 168 | 0 | Public BookThatApp explicit occurrence schedule and 31 complete Shopify product narratives; one product detail read per run, native blackouts honored. |

The 27 held occurrences comprise 26 absent/placeholder/URL-only native descriptions and one Castle Island Friendsgiving event without a resolvable venue. The exact held titles and URLs are in the JSON evidence. No narrative is generated from a title or category. Full upstream blank bodies remain explicit holds. Source calendars contribute only explicit dates within the collection window; no weekday recurrence is invented. BookThatApp custom announcements are not treated as scheduled product events.

## Venue resolution evidence

| Venue | Structured address | Official evidence |
|---|---|---|
| Aeronaut Somerville | 14 Tyler Street, Somerville, MA 02143 | https://www.aeronautbrewing.com/visit/somerville/ |
| Notch Brighton | 525 Western Avenue, Brighton, MA 02135 | https://www.notchbrewing.com/notchbrighton |
| Remnant Brewing | 2 Bow Market Way, Somerville, MA 02143 | https://www.remnantsomerville.com/live |
| Remnant Satellite | 877 Cambridge Street, Cambridge, MA 02141 | https://www.remnantsomerville.com/live |
| Castle Island South Boston | 10 Old Colony Avenue, South Boston, MA 02127 | https://www.castleislandbeer.com/southie |
| Castle Island Norwood | 31 Astor Avenue, Norwood, MA 02062 | https://www.castleislandbeer.com/norwood |
| The Bebop | 1116 Boylston Street, Boston, MA 02215 | https://www.thebebopboston.com/new-events |
| Lamplighter Broadway | 284 Broadway, Cambridge, MA 02139 | https://lamplighterbrewing.com/pages/284-broadway-taproom ; https://lamplighterbrewing.com/pages/privacy-policy |
| Lamplighter CX | 110 North First Street, Cambridge, MA 02141 | https://lamplighterbrewing.com/pages/110-n-first-street-cx-taproom |
| Club Café | 209 Columbus Avenue, Boston, MA 02116 | https://www.clubcafe.com/club-events/ |
| Boston Public Market | 100 Hanover Street, Boston, MA 02108 | https://bostonpublicmarket.org/visit/ |
| Dorchester Brewing | 1250 Massachusetts Avenue, Boston, MA 02125 | https://www.dorchesterbrewing.com/events/ |
| Pandemonium Books & Games | 4 Pleasant Street, Cambridge, MA 02139 | https://pandemoniumbooks.com/pages/contact-us |

Only four exact publisher street-matching points are retained: Remnant Satellite, both Castle Island venues, and The Bebop. Other records explicitly await the shared geocoder; no coordinates are invented. Notch's copied Salem marker and Squarespace's New York placeholder are rejected. Lamplighter CX's street is explicit in its venue page; its postal code is completed from local address context pending geocoder confirmation. The other normalized addresses are directly supported by the linked publisher pages/calendars.

## Transport and discovery holds

- **Roundhead Brewing:** official event calendar and robots return an HTTP 202 captcha/challenge. No alternate challenge bypass or production source is registered.
- **Tavern of Tales / Alpha Omega Hobby:** official Google calendars were located, but `calendar.google.com/robots.txt` disallows calendar exports. No Google export ingestion is added. Tavern is at 1478 Tremont Street, Boston, MA 02120; an accessible independent publisher feed remains needed.
- **Squarespace exports:** the Notch, Remnant, Castle Island, and Bebop robots rules disallow JSON/ICS query routes. Their accepted collectors use normal HTML instead.
- **Boston Public Market:** `/wp-json/` is disallowed, and the nominal ICS route returned HTML. The accepted collector follows the visible public calendar/detail HTML.
- **Pandemonium:** the official calendar itself names `https://pandemonium-books-games.bookthatapp.com/availability/schedule.json`; that host's robots disallows only `/navigate`. No checkout, registration, inventory change, or private endpoint is used.
- **Bow Market:** the examined `/events` page did not supply a usable dated event feed. Newsletter announcements alone were not expanded into assumed recurrences.
- **Pinball Over Boston:** the examined event/news entry was stale (2021); no future calendar inferred.
- **Harpoon:** excluded from new scope because the parent production review identifies it as already working.

Dedicated gaming coverage is supplied by Pandemonium's card tournaments, D&D sessions, wargaming, and hobby nights, with additional explicit Flagons & Dragons events at Aeronaut, mahjong at Castle Island, and queer board-game events at Club Café.

## Verification

`python -m pytest tests/test_boston_nightlife.py -q` passes 13 focused tests. They cover long full narratives, no second HTML parse of normalized text, native blanks, Brighton versus Salem location, multi-venue ambiguity, overnight clocks, source/media scoping, complete-batch checkpoint output, checkpoint mutation and expiry, request budgeting, all-day closure filtering, explicit gaming occurrence dates, blackout suppression, and one narrative read per repeated product.

All ten full capture replays completed: Aeronaut/Notch/Remnant/Castle in one chunk each; Bebop in six; Lamplighter and Club Café in three each; Public Market in eight; Dorchester in two; Pandemonium in seven. Checkpoints cap each source at 200 manifest items and expire after four hours. Every chunk passed the shared database wire guard. Capture hashes and full expected record metadata are in the adjacent JSON evidence; full narrative rows remain in the task capture directory for batch publication comparison.
