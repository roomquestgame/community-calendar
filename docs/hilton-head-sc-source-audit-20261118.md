# Hilton Head Island SC — 15-source audit, November 18, 2026

Five genuinely new direct feeds verified in a bounded read-only collector dry-run, 10 technically held. A successful HTTP page alone does not authorize a new production feed. The source registry search found no previously registered Hilton Head-specific first-party source keys or URLs. Existing FindLocal and regional source traffic must not be duplicated.

| # | First-party organizer | Feed type and current status | Valid dated street-resolved full-description candidates |
|---|---|---|---:|
| 1 | Hilton Head Symphony Orchestra | https://hhso.org/events/?ical=1 — ICS admitted; 27 raw VEVENTs | 3 |
| 2 | Culture HHI / Office of Cultural Affairs | https://culturehhi.org/events/?ical=1 — ICS admitted; 10 raw VEVENTs | 3 |
| 3 | Island Recreation Association | https://www.islandreccenter.org/events?format=json — Squarespace admitted; 7 upcoming; blank locations/long content held | 1 |
| 4 | Shelter Cove Harbour & Marina | https://www.welcometosheltercove.com/calendar-of-events?format=json — Squarespace admitted | 8 |
| 5 | Lincoln & South Brewing | https://www.lincolnandsouth.com/events?format=json — Squarespace admitted; 13 upcoming; blank locations/default NYC points held | 7 |
| 6 | Coastal Discovery Museum | https://www.coastaldiscovery.org/explore/events/ — hold: Tribe REST 404, ICS 0 VEVENT, HTML activity parser needed | — |
| 7 | Art League of Hilton Head | https://shop.artleaguehhi.org/module/events.htm — hold: ShopKeep HTML and class-specific gallery/academy venue resolution | — |
| 8 | Arts Center of Coastal Carolina | https://www.artshhi.com/ — hold: theater/ticketing event API and dates not yet verified | — |
| 9 | The Jazz Corner | https://thejazzcorner.turntabletickets.com/ — hold: booking HTML and event details need verification | — |
| 10 | Hilton Head Chamber | https://hiltonheadchamber.org/events/community-events — hold: aggregator HTML; unverified JSON path returned 406 | — |
| 11 | Hilton Head municipal calendar | https://hiltonheadislandsc.gov/our_island/special_events/index.php — hold: robots status unverified | — |
| 12 | Beaufort County Library | https://www.beaufortcountylibrary.org/ — hold: presumed /events route 404, LibCal robots status unresolved | — |
| 13 | Sea Pines Resort | https://www.seapines.com/experiences/events — hold: generic HTML, no tested event-specific structured feed | — |
| 14 | Lean Ensemble Theater | https://www.leanensemble.org/ — hold: guessed Squarespace /events JSON 404 | — |
| 15 | Hilton Head Distillery | https://hiltonheaddistillery.com/events — hold: route 404, no verified event feed | — |
| | **Total** | **5 direct feeds / 10 holds** | **22** |

The 22 figures are first-pass future candidate records only, not public EventQuest cards. Preserve verified actual event addresses: First Presbyterian Church 540 William Hilton Pkwy; St. Gregory the Great Parish Life Center 31 Saint Gregory Drive in Bluffton; Shelter Cove Community Park 39 Shelter Cove Lane; Shelter Cove Towne Centre 40 Shelter Cove Ln; Shelter Cove Harbour and Marina 1 Shelter Cove Ln; Lincoln & South Brewing 138 Island Drive. Do not place events at an organizer center. The only venue-name correction made is HHSO's First Presbyterian Church shortened '540 William Parkway' to verified '540 William Hilton Pkwy'.

New collector reuses existing ICS time/recurrence and Squarespace JSON parsers. It retains full sanitized publisher text to 12,000 characters and holds longer or missing text, verifies URL host and event identity, refuses missing numbered streets, and drops the Squarespace NYC placeholder coordinate. iCalendar ATTACH and Squarespace image asset URLs are preserved only as rights-gated publisher candidates after host/thumbnail checks, not a blanket image publication license. Event and venue categories go through the existing EventQuest shared 25-category classifier; uncertain categories need specific post-staging trigger fixes, not arbitrary Other/default assignment.

Initial read-only classifier title+short-description probes: Holiday Pops and Live Music map to music, Oyster Roast maps to food_drink; Nutcracker, Community Market, Winter Wonderland and Santa Day were not suggested in stripped-down probes. Re-evaluate the full event descriptions and publisher category labels after staging; amend the existing classifier only in a separate coordinated migration, without touching running backfill cursors.

For production: collector PR, passing focused tests and Vercel READY; then one forward-only migration for approved verified source keys, guarded source publication/street/photo and category checks, and queued previews; then validate staged vs published counts, dedupe, descriptions, verified event-specific streets, category-null/Other and thumbnails. Current Postgres17 baseline and other city/provider records remain untouched. No routine per-source GitHub Actions runs.

Follow-up: implement the 10 held venues only after a supported publisher endpoint/event-level facts and robots/rights check exists. An HTML 200 or regional aggregator listing is not sufficient.


## 2026-11-18 exact Parish Life Center address correction

HHSO's venue URL `https://hhso.org/locations/st-gregory-the-great-parish-life-center/` supplies `31 Saint Gregory Drive, Bluffton`, also used by the *St. Gregory the Great church/parish office*. However the **Beaufort County Board of Voter Registration and Elections**, which actually uses the **Parish Life Center** as a polling location, repeatedly and explicitly lists that **particular facility at `32 Saint Gregory Dr, Bluffton, SC 29909/29910`**. Official source: https://www.beaufortcountysc.gov/vote/Polling%20Locations%20--%20School%20Board%20District%207%20Special%20Election.html; the county 2017 project-site plan and 2026 notices corroborate number 32. This is an **actual verified distinction between two related venues**, not a street-number guess.

Only the exact HHSO iCalendar location `St. Gregory the Great Parish Life Center, 31 Saint Gregory Drive, Bluffton, SC` is corrected to `32 Saint Gregory Dr, Bluffton, SC`; generic churches, unrelated venues and the official 31 church-office address stay untouched. The normal event geocoder evaluates the **corrected numbered venue**. No supplied geocoordinate is inferred from the church, neighboring Catholic school or city center; the event must remain pending if Geocodio cannot resolve the 32 address precisely enough. No client UI, category rules, direct event edits, PostgreSQL migrations, robot policy exceptions or image rights changed in this collector PR.

A same-source first-collection replay is required after the corrected collector reaches production; the earlier 31-street staged snapshot must not be considered complete under this new venue evidence. Existing publication/dedupe retains source/recurrence identities.
