# Anchorage, Alaska primary event source audit — 2026-11-18

## Production baseline and scope

Collector evidence and local, read-only Supabase evidence are separate. The read-only database query returned **zero** future, geolocated external events within 25 miles of downtown Anchorage across the next 60 days. Existing municipal source registry includes Anchorage Park Foundation (approved, last success October 28; no visible external event rows by that source key) and Alaska Botanical Garden (paused, failed venue extraction). Neither is a new source to duplicate. Preserve the former and repair the latter in place.

This batch adds a **publisher-specific library calendar** and a **repair adapter for the existing Garden source** to the Udell community-calendar collector. No automatic production publication or publisher rights approval occurs in this repository. The Supabase source registry, permissions and separate deploy gates remain authoritative.

| Direct source | Exact publisher endpoint | Parser | Dry-run upcoming pass | Correct venue street | Images | Status |
|---|---|---|---:|---|---|---|
| Anchorage Public Library | https://anchorage.librarycalendar.com/events/feed/ical | existing iCalendar/VEVENT with branch-address normalization | **151** | 5 verified library branches, per-record | no image provided by tested feed | Collector ready; source registration/publisher-rights review required |
| Alaska Botanical Garden | https://www.alaskabg.org/upcoming-events-workshops?format=json | existing Squarespace JSON fields | **7** | official Garden street for onsite listings | 7 original-size publisher image candidates; image rights unreviewed | Repair adapter ready; existing paused registry row requires gated re-enable |
| Anchorage Chamber | https://business.anchoragechamber.org/api/events | GrowthZone XML candidate | not publishable: 240 raw rows | requires event-specific detail resolution | not validated | withheld: robots.txt HTTP 403; per-event details and rights unreviewed |
| 49th State Brewing, Anchorage | https://www.49thstatebrewing.com/wp-json/tribe/events/v1/events | WordPress Events Calendar JSON candidate | not publishable: 5 raw rows observed | some event JSON venue arrays blank; onsite/away need validation | WordPress featured media candidate | withheld: robots.txt HTTP 403; rights and event-specific venue review |
| Anchorage Park Foundation | https://anchorageparkfoundation.org | existing WordPress source | not reimported by this batch | existing | existing | already registered; separate operational issue |
| Visit Anchorage | https://www.anchorage.net/events/ | tourism aggregator | not tested as direct publisher | mixed, requires dedupe | unverified | lower priority than original organizers |
| Anchorage Museum | https://www.anchoragemuseum.org/visit/calendar/ | calendar/UI; structured endpoint unconfirmed | untested | 625 C Street, Anchorage AK | unverified | structured endpoint discovery needed |
| Alaska Center for the Performing Arts | https://alaskapac.org/events/live-music | public venue listings; structured endpoint unconfirmed | untested | 621 W Sixth Avenue, Anchorage AK | unverified | structured endpoint discovery needed |
| Alaska Zoo | https://www.alaskazoo.org/public-event-calendar | public calendar; structured endpoint unconfirmed | untested | verify each event | unverified | structured endpoint discovery needed |
| The Side Quest | https://thesidequestak.com/ | local gaming calendar / Google calendar widget | untested | 1300 E 68th Ave #102, Anchorage AK | unverified | ICS subscription/distribution review |
| UAA Seawolves | https://goseawolves.com/sports/mens-ice-hockey/schedule | athletic schedule | untested | separate home/away game arenas | unverified | structured schedule and home-game filter review |
| Nerdvana Trivia | https://nerdvanatrivia.com/venues/ | weekly organizer listings | untested | rotating bars; verify per show | unverified | no validated dated feed; do not fabricate occurrences |
| Anchorage Farmers Market | https://www.anchoragefarmersmarket.org/ | seasonal first-party calendar | 0 upcoming verified | seasonal market site | unverified | 2026 market season ended; wait for dated 2027 schedule |

## Reproducible publisher dry-run evidence

2026-11-18 sandbox test: the Library's direct 258-kB iCalendar download contained **304 VEVENT** records and normalized to **186 future** events before venue/description/category gates. **151** passed all those gates. The 35 held include 2 source records with missing descriptions plus unverified/offsite venue and uncertain event categories. The five accepted branches (verified by the publisher) are:

- Z.J. Loussac Library — 3600 Denali Street, Anchorage, AK 99502.
- Chugiak-Eagle River Library — 12001 Business Blvd #176, Eagle River, AK 99577.
- Muldoon Library — 1251 Muldoon Road Suite 158, Anchorage, AK 99504.
- Mountain View Library — 120 Bragaw Street, Anchorage, AK 99508.
- Scott & Wesley Gerrish Library — 250 Egloff Drive, Girdwood, AK 99587.

Accepted Library primary categories: learn (99), give_back (15), sports (6), hang_out (6), movies_theater (2), create (23). **No Other/default** classifications. Descriptions nonempty, sanitized, untruncated; measured lengths 63–895 characters. All accepted events have nonempty verified street addresses and local IANA timezone America/Anchorage. No source-centroid coordinates are inserted.

Garden Squarespace JSON contained **7 future upcoming** publisher events, all passing the current source-specific validation. Full descriptions measured 400–1,285 characters; original-size image URLs appear in the API for all 7 as **candidates**, not permissions. The Squarespace generic New York pin (40.7207559,-74.0007613) was rejected. Physical Garden venue: **4601 Campbell Airstrip Road, Anchorage AK 99507**; only nonconflicting onsite listings are eligible. Time fields are publisher-supplied Unix milliseconds and are converted to UTC instants with America/Anchorage as the displayed zone. No invented street number or source-wide map point is used.

Repeat fetches use stable publisher UID and occurrence timestamps. Unknown event activities/addresses are held for Admin curation, not labeled Other. The shared recurrence expander retains a 60-day window. This is a **collector dry run**, not a claim of visibility in EventQuest.

## Batch deployment/rights audit

- No new collector engine: existing iCalendar parser, Squarespace JSON parser, shared description sanitizer, publisher identity and photo-evidence hooks.
- Worker guarded by exact source_key, feed URL, adapter, kind and America/Anchorage; robots checking and host allowlists in existing fetcher.
- Images remain subject to licensed-image and full-resolution byte probing before public rendering.
- Excluded entries retain explicit machine-readable log reason codes: missing/oversized description, unverified venue, unknown category, source URL mismatch, unsupported event timing, nonpublic or offsite.
- Source description and coordinates must be independently verified after Supabase staging, geocoding and publication.
- Do not enable new sources as approved without source-rights review or publish image candidates automatically.
- Production PR checklist (app/backend repo): source row, exact source support and event identity, full-description staging, venue-geocoder path, classification trigger checks, regression, dry run, single migration, deployment, read-only published event query, visual card verification.

No CAPTCHA/Cloudflare workaround was attempted; sources that serve 403 robots checks remain withheld.


## Follow-on Anchorage publisher batch — November 18, 2026

Only sources *not already working in production* are included. Anchorage Public Library (151 published), Alaska Botanical Garden (7), and the existing Anchorage Park Foundation are not copied or registered again.

| New primary publisher | Structured feed | Collector type | Dry-run eligible future events | Narrative, street and media |
|---|---|---|---:|---|
| Alaska Zoo | https://www.alaskazoo.org/event-calendar?month=december-2026&view=calendar&format=json | Existing Squarespace JSON monthly items; three bounded calendar months | **30** | 8 learn / 11 gardens_nature / 11 festival; 109–1,404 description chars; 4731 O'Malley Road, Anchorage AK 99507; venue-provided coordinates (61.1236344,-149.7908746); sampled original image HTTP 200, PNG 1080×1080 |
| Cook Inlet Historical Society | https://www.cookinlethistoricalsociety.org/lecture-series?format=json | Existing Squarespace upcoming-event JSON | **1** | Learn; full 3,242-char description, official Anchorage Museum 625 C Street, Anchorage AK 99501 and publisher map 61.215893,-149.8846999; sampled image HTTP 200, JPEG 800×450 |

The Zoo month pages had 18 November, 20 December, 3 January records. After 60-day/date, uniqueness, category, verified street/location and public-attendance filters, **30 eligible** remain. No duplicate occurrences, blanks, truncated descriptions or source-wide map pins. Promotions, private/member-only listings and invalid/offsite records are excluded. The Historical Society publisher's venue address used ZIP 99508 despite explicitly identifying 625 C Street at Anchorage Museum; the Museum's own official address is **99501**. We require the publisher's correct venue name/street and use the independently verified postal code; we never invent a street number. Source photos are candidates only, rights unreviewed.

### Other primary organizers checked but not enrolled

| Source | Reason withheld |
|---|---|
| UAA SeawolfLife public ICS — https://uaa.campusgroups.com/ics_helper | 620 raw VEVENT entries; 97 future parsed, but 73 future entries say "Sign in to download the location". The final ICS CDN host returned robots.txt 403 and the existing safe collector fetch returned dns_unavailable. Do not bypass access checks or fill private venue fields |
| Anchorage Museum — https://www.anchoragemuseum.org/visit/calendar/ | Live first-party events and planetarium listings found, but a structured endpoint is not verified; retain as pending native API/ICS discovery, not a new unreviewed HTML scraper |
| CenterTix / Alaska PAC — https://centertix.com/events/ | Live performances, but public structured endpoint unavailable/unverified; timeout during JSON probe; investigate safe presenter-specific feed |
| 49th State Brewing — https://www.49thstatebrewing.com/anchorage/ | Earlier audit found 5 raw TEC API events; robots.txt returned 403 and event-level venue addresses were incomplete |
| Anchorage Chamber — https://business.anchoragechamber.org/api/events | GrowthZone XML endpoint returned 240 raw entries; robots.txt 403 and event venue resolution incomplete |
| Koot's — https://koots.com/ | Recurring weekly formats only, no verified upcoming dated machine-readable feed; don't manufacture recurrence dates |
| Williwaw Social — https://williwawsocial.com/welcome/ | Official site says permanently closed; exclude completely |

The 31 eligible events were validated directly against official publisher responses using the existing EventQuest sanitizer, date/timezone conversion, source-identity bounds and verified event venue points. Both current and new Anchorage adapter suites passed **13 pytest tests**. Both image samples resolved successfully but must not be published without appropriate image rights. Production collection and public visibility require a separate guarded source-registry release.
