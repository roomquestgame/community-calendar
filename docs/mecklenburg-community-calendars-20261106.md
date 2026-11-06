# Mecklenburg community calendar batch — November 6, 2026

[EVE-41](https://linear.app/eventquest/issue/EVE-41/next-mecklenburg-batch-coopers-landing-clarksville-tourism-and-good) adds three reviewed public sources to the existing HTML collector. This is implementation evidence; the manual shared-transport audit, final-head CI, collector deployment, companion database deployment and actual public readback must be recorded before claiming release.

## Sources and verified publisher facts

| Source | Registered discovery URL | Captured 60-day candidates | Venue |
| --- | --- | ---: | --- |
| Cooper's Landing | https://cooperslandinginn.net/?page_id=119 | 1 | 801 Virginia Avenue, Clarksville, VA 23927 |
| Clarksville Tourism | https://tourism.visitclarksvilleva.com/calendar/ | 1 | Cookie & Cocoa Crawl check-in: 321 Virginia Avenue, Clarksville, VA 23927 |
| Good Shepherd Drops of Love Food Pantry | https://goodshepherdsouthhill.org/welcome/calendar/ | 8 | 1664 N. Mecklenburg Avenue, South Hill, VA 23970 |

Source keys are `coopers_landing_clarksville_va`, `clarksville_tourism_va` and `good_shepherd_food_pantry_south_hill_va`. All use `kind=html`, `platform_adapter=html`, the existing HTML demand worker, staged candidates and v3 snapshot certification. No cron, parallel event store or new collector category is added.

Cooper's explicit 2026 cooking-school schedule supplies December 7, 6:30–8:30 p.m. Eastern, Holiday Entertaining & Heavy Hors d'oeuvres. The 6 p.m. reception is separate. The class is $85 plus tax, with optional paired wines extra and advance reservation terms. Its general upcoming-events page mixes undated offers, so it is not used to infer years.

Tourism's bounded Locable catalog visits five pages and the ten relevant future details in the current capture. Visible details must agree with their embedded calendar data; the latter is parsed locally rather than fetched as another feed. The final December 5 Cookie & Cocoa Crawl runs 10 a.m.–3 p.m., costs $40, and begins at Town Hall (check-in ends at noon). Stable occurrence ID667469 supersedes the specifically reviewed ID636949 teaser only with corroborating identity. A cancelled final cannot cause that teaser to reappear. Eight poker occurrences are held for conflicting Poker/Pool narratives and 600/601 Virginia Avenue addresses. The parser never converts catalog absence or a hold into cancellation.

Good Shepherd uses its observed public WordPress ICS Calendar display action. The worker injects a narrowly bound render callback: one fixed host/path and form action, with fresh nonce/argument tokens from current markup. Parsers cannot select arbitrary POST destinations or actions. Existing public DNS, robots, pacing, response limits, strict encoding, deadlines and Retry-After checks apply; POST redirects are rejected. The calendar must contain complete, correctly labeled day grids. Only explicit Food Pantry dates are imported: November 10/17/24 and December 1/8/15/22/29, 10:30 a.m.–noon, corroborated by https://goodshepherdsouthhill.org/ministries/food-pantry/. January 5 is not present and is not generated. Price remains unknown. Parish services, closures, travel bookings and untimed sales are excluded.

## Shared capabilities

Event narratives and exact official evidence links reach normal classification. Explicit same-occurrence cancellation/postponement is retained; missing future dates never withdraw events. The companion backend preserves real demand, publication rights, source holds, address waiting/resumption, freshness, manual category overlays and canonical public readers.

Only Tourism supplies an event-specific artwork candidate, using the actual Locable image path format. The same media worker must verify bytes before display. Cooper's and Good Shepherd have no verified event artwork; shared banners and logos are not substituted. Addresses are sent through the existing verified geocoder/cache. Source coverage circles are discovery coverage only, never event coordinates.

## South Hill geocoding review

Production readback at 15:36 UTC found an enabled, unpaused worker, 48 resolutions and 21 ambiguous outcomes in 24 hours, using 87 of 2300 daily reservations. The two Town keys each have one finalized ambiguous attempt and no active claim. Runtime logs confirm successful claim/reserve/fail RPCs followed by another address's successful submit in the same invocation. No provider response or detailed rejection reason was retained, so the original ambiguity cause cannot be distinguished retrospectively.

The Python review found overescaped regular expressions when splitting ZIP codes from state components. The narrow correction and focused regressions preserve candidate precision, street/state/ZIP matching, request reservation and lease behavior. Both current Town queue strings omit ZIP codes; this separate defect does not explain their original ambiguity or authorize resetting attempts.

The current town agenda confirms the temporary council venue at 111 E. Danville Street, South Hill, VA 23970. The town calendar links a selected address pin at latitude 36.7244269, longitude -78.1295057. Virginia Tourism Corporation’s official Centennial Park listing confirms 225 E. Danville Street and a named venue point at latitude 36.7239802, longitude -78.128577. The companion backend prepares a bounded repair for these two exact cache keys, preserving attempt/request/quota/ambiguity history and resuming through normal publication gates. Map viewport centers and the old Town Hall address are excluded. See the companion backend’s docs/evidence/south-hill-venues-20261106.json for the source chain and captured hashes.

## Verification and release limits

Captured raw markup is retained as bounded public fixtures with receipts. Local parser, transport, evidence, status and shared pipeline tests run before CI. The public audit script calls only `preview_source`; it does not stage, publish, register, fabricate interest, authenticate to the database or probe images. Local shared transport returned `dns_unavailable`, so the manual GitHub audit is required to establish actual collector network behavior without bypassing that guard.

### Live readiness findings and narrow follow-up

[Diagnostic run 42248590568](https://github.com/roomquestgame/community-calendar/actions/runs/42248590568), at collector revision `2d1513d`, observed Tourism complete with one candidate and one image candidate. Cooper's request stopped at robots retrieval with HTTP403. Cooper must remain paused with discovery routing disabled; the final readiness audit skips its network collection and records the exact prior `robots_denied` hold and evidence run. It does not retry the publisher or change headers, routes or robots handling.

Good Shepherd returned one valid calendar after one canonical-page GET and one fixed render callback. Its rendered DOM ID differed from the placeholder ID, with no pagination and all six month grids present. The publisher's observed [front-end script](https://goodshepherdsouthhill.org/wp-content/plugins/ics-calendar/assets/script.min.js) inserts that response into the requesting placeholder without comparing these display IDs. The [plugin changelog](https://icscalendar.com/changelog/) describes auto-generated DOM identifiers separately from calendar data; the [caching documentation](https://icscalendar.com/faqs-and-tips/) also describes separately cached calendar data. The diagnostic establishes the actual ID mismatch; it does not establish which server cache produced it.

The follow-up removes only equality between the two response DOM IDs. The discovery page still needs its exact canonical URL and single reviewed placeholder; its exact current nonce/argument tokens still go to the fixed source-specific render callback. The returned calendar must retain a valid ID and internally consistent selector/month/day/event references, complete date grids, bounded rows, no pagination, the current date window and the reviewed pantry ministry facts. Occurrence identity remains based on the published pantry date, never the display ID. Invalid or duplicated calendars, stale or clipped grids, different source identities and conflicting pantry facts remain rejected or held under their existing rules.

The sanitized live artifact verifies all 199 grid row counts and the eight visible upcoming pantry dates/times. It intentionally omits original event date/time classes and unrelated event contents, so it is not raw parser input. The full-capture regression instead changes every DOM reference coherently to a new synthetic valid ID and verifies unchanged eight-occurrence output and request arguments. `tests/fixtures/mecklenburg_batch3/good_calendar_dynamic_id_observation.json` records the live observation and diagnostic artifact hash. A final audit of the current unsanitized response remains the activation gate.

The readiness receipt distinguishes `complete` from `active_complete`: the former remains false while Cooper is held; the latter requires both intended-active Tourism and Good Shepherd to finish successfully and controls the audit's exit status. A held row has `network_skipped=true`, `complete=false` and its evidence receipt. A successful readiness audit does not activate or publish any source.

Library, SVCC/Blackthorn and other previously held sources remain held. South Hill Chamber remains pending with routing disabled after HTTP403. Keep this source-access hold distinct from Town address ambiguity. No app UI or mobile OTA change belongs to this batch.

