# Iowa/Nebraska reviewed source batch — November 6, 2026

Ben approved this expansion and QA batch. Release is pending; this is implementation and qualification evidence, not a claim of production enrollment.

## Ready for staged enrollment

- **Experience Waterloo**: HTML calendar advertises a public read-only search index. Collector discovers its public search key from that page at runtime, binds the exact index and hostname, completes bounded pagination, and keeps complete timed physical occurrences with their own numbered Iowa address. The index encodes local wall clocks as UTC-shaped epochs; canonical hockey and Storytime pages establish Chicago conversion. Thirteen current records qualify. Unverified index GPS is discarded: the Lights the Night record points to Colorado. Multiday displays and incomplete/multiple-location addresses are withheld. Original publisher S3 images remain unverified candidates until the shared byte probe.
- **Bellevue Chamber and Clear Lake Chamber**: retain XML/GrowthZone in the existing dedicated ChamberMaster collector, daily budget and on-demand path. Their reviewed parser uses each record's own approved/Public flag, schedule, narrative and complete locality; it never inherits recurrence facts from a parent/title. This avoids per-event ICS requests and the old 20-detail ceiling. Numeric category IDs are not activity labels. Default 23:55/23:59 ends become unknown; continuous multiday displays are withheld. Explicit public opening receptions may qualify independently. Missing addresses remain withheld. Bellevue's exact publisher-embedded Bellevue Together Firespring artwork is a candidate; Google search thumbnails, embedded data images and unrelated assets are rejected. Clear Lake supplies no accepted event photo candidate.

New registrations start pending, without fabricated demand or venue coordinates. Census city circles route source discovery only; each occurrence must pass the shared address resolver. Tests check actual searched-area matching, not merely enabled=true. Database support must deploy before this collector version is activated for the new sources.

## Candidate qualification holds

- **Discover Ames**: calendar, TEC endpoint and robots return bare HTTP403. No cause is assumed; do not evade the response or enroll an unvalidated feed.
- **Meet in Marshalltown / Chamber**: public TEC API and publisher-linked GrowthZone detail pages work. Four records in the current 60-day export fail enrollment quality: Trivia and Craft Show have no actual descriptive narrative; Jingle & Mingle specifies a district without a street address; Holiday Stroll has a 2PM structured start against 4PM in narrative and multiple attendance venues. Do not invent a venue or choose a conflicting start.
- **Bellevue City/Library**: official library ICS is a valid empty calendar. City ICS contains all-day holiday closures, not eligible timed physical attendance. Existing Bellevue Times is not duplicated.
- **Fontenelle Forest**: own calendar publishes 38 current-month JSON-LD records with empty descriptions and no locations. Most link through two Social Good Software redirects to public Blackbaud forms; a SUN form verifies real narrative, date/time, venue and conditional admission. Thirty-two current/future records would require over 60 same-host redirect requests, beyond the collector's bounded source deadline with normal publisher pacing. Its own remaining future event is a Nature Center closure. Enrollment is held for a bounded resumable registration-detail integration; no partial snapshot or invented forest-default pin is released. The queried TEC/ICS endpoints return403; own calendar robots disallows query URLs and specifies a three-second delay. No registration is submitted.
- **Independence**: official library ICS and the known detail still404. The existing venue-label fix remains deployed; no fresh upstream acceptance is claimed and retained valid data is not force-paused.

## Mason City retest

Ten active public occurrences have publisher-matching start/end times, titles, descriptions and venue names; all ten have photos and there are no duplicate provider occurrence keys. Eleven occurrences qualify in the current bounded first page; four timezone-conflicting records remain withheld. Eight public occurrences have no recognized category; the shared classifier gains explicit narrative rules for documentary screenings, participatory music jams and hands-on pottery classes. Negative tests cover health screenings, food jam, sales and incidental music. Shopping/collectible shows remain uncategorized where the existing taxonomy has no supported specific activity; no sports classification is inferred from sports memorabilia. Targeted repair preserves manual corrections. First-page omission still cannot imply cancellation.

## Iowa City address review

Ten address keys remain explicitly ambiguous in Geocodio; retained evidence contains no accepted point. Examples include Chauncey Swan Park, Tailgators, North Liberty venues, Iowa Memorial Union and suite-bearing addresses. Source-city centers are not substitutes. No provider secret is read, quota/demand gate bypassed, confidence requirement weakened or failed address silently marked resolved. These remain event-level holds pending exact primary venue/map evidence or a valid provider match.

## Validation

Pinned production Python dependencies: complete local suite **1222 tests and 37 subtests passed** before the final regression additions. New Waterloo/Chamber tests use real public snapshots with embedded data-image payloads removed. No runtime search key is committed.

A local PGlite/PostGIS rehearsal rebuilt all **290 current main migrations**, then applied the new migration and exercised public collector RPC staging, certification, approval/hold behavior, address-only waiting/resolution/resume, real coverage matching, factual publication, verified-image submission, repeat identity, categories and free-cost evidence. This is an isolated migration/behavior rehearsal, not the production live-schema simulation. GitHub required checks and guarded live rehearsal/deploy remain mandatory.

Twenty-two existing SQL behavior files across ChamberMaster, Iowa, Virginia, MyCountyParks, geocoding, classifications, publisher media, scheduling, and coverage passed in the isolated rehearsal. Eight initially required the runner to handle psql `\\echo` output directives; their unchanged SQL assertions then passed. The new end-to-end batch behavior file also passed, including both XML-as-ical photo publication and HTML photo publication. Final full Python suite: **1222 tests, 37 subtests passed**.
