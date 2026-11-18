# Gainesville, Georgia — direct first-party calendar intake (November 18, 2026)

## Publisher selection: Localist and existing adapters before Mapsee

**Owner correction:** Use the publisher's native Localist, WordPress TEC REST,
iCalendar/ICS, LibCal RSS or Squarespace JSON endpoint where available.
Mapsee is discovery/catalog evidence only, never the preferred transport.
Do not re-enroll existing Mapsee sources that already publish in EventQuest.
Existing Atlanta Botanical Garden source
`municipal_mapsee_bca3f9771310e5a061ca6188` is left intact to avoid doubles.
The University of Georgia's preexisting Localist listing is untouched.

**Optional content:** A missing publisher image or description is not a reason
to suppress an otherwise valid public event. If the publisher provides
description text, sanitize and retain all of it within the existing scoped
12,000-character contract: never silently shorten it. An oversized narrative
requires review, not truncation; an absent narrative is represented as ''.
Images are candidates only, subject to rights/byte checks; existing fallback
artwork remains when no eligible image exists.

## Combined source audit

| Source | Native type | Actual 2026-11-18 bounded collector dry run | Address | Description | Image candidates | Next action |
| --- | --- | ---: | --- | --- | --- | --- |
| Explore Gainesville official events | WordPress Events REST JSON | **36** | 36 publisher event streets, use existing geocoder | 36 full sanitized | Source photo candidates, optional | Existing first-batch adapter, backend registration |
| Blackstrap Rock Hall | Squarespace JSON | **7** | 7 published streets + native coordinates | 7 summaries | 7 | Existing first-batch adapter, backend registration |
| Brenau University public events | WordPress Events REST JSON | **7** | 7 publisher-numbered GA streets | 7 complete (344–772 characters after HTML cleaning) | 7 | New publisher adapter, backend registration |
| Gainesville Library on the Square | LibCal RSS | **42** | 127 Main St NW, Gainesville GA 30501, officially verified for exact campus only | 40 present, 2 absent but still eligible | None offered | New library-native adapter, backend registration |
| Meeple Madness, Flowery Branch | Tockify iCalendar | **119 parsed** from 571 feed components, but **0 admitted** | First-party event feed confirms 7400 Spout Springs Rd Suite 205, matching store | Complete; no images | None | **Hold:** `tockify.com/robots.txt` and publisher calendar-host `robots.txt` both disallow automated feed access. Never circumvent. |

The 92 records from the first four are **before** category enrichment, precise-coordinate
geocoding and cross-source deduplication; **not** a count of newly published cards.
The two blank-description library events pass the corrected optional-content rule.
Some 2026 LibCal all-day placeholders are excluded because midnight-to-23:59
doesn't establish public opening hours.

## Other reviewed sources not yet enrolled

- Atlanta Botanical Garden has existing production source coverage; don't duplicate.
- Humane Society of Northeast Georgia TEC REST contains four dated listings but
  no event-level venue street; source pending venue resolution.
- Lake Lanier Association TEC REST returned zero events for the checked 30-day window.
- Hall County CivicPlus publishes official iCalendar feeds; several live meetings and
  Chicopee Ag Center entries need event-specific address and category checks.
- Greater Hall Chamber and NoFo Brew remain on publisher access/endpoint review.
- The Arts Council Squarespace JSON has few near-term street-resolved entries.
- Meeple Madness direct Tockify ICS is held on robots grounds even though it is
  machine-readable. HTML fallback only if publisher permits and complete fields
  can be validated; do not treat the API denial as permission to scrape.

## Security, limits, and verification

- Source-key/profile, URL host and path are exact allowlists; no user-supplied URLs.
- Publisher transports honor robots, pacing, HTTP caps, SSRF and redirect checks.
- Only actual event venue coordinates/verified streets; no source-wide map pin.
- Preserve actual local timezone, cancellation, recurrence instances and original links.
- Missing/unlicensed images fall back; descriptions supplied are kept in full.
- Global shared classification is the only normal categorization path; source venue
  labels don't become blanket event overrides. Classification gaps must be
  reviewed/trigger-improved, not assigned arbitrary categories.
- The collector release carries no DB SQL, no new scheduled GitHub Actions jobs,
  no UI or production event writes. One follow-up app-repo migration covers all four
  eligible source registrations and preserves the already-squashed PG17 baseline.
- Focused tests: **19 passed** for direct source identity, full/optional text,
  exact venue, image sanitization, all-day holds and shared ICS recurrence handling.

### External verification

- Meeple official venue: https://meeplemadness.com/contact-us/
- Hall County government HQ/library location: https://www.hallcounty.org/Facilities/Facility/Details/Hall-County-Library-Headquarters-74
- Direct publisher feeds:
  - https://www.brenau.edu/wp-json/tribe/events/v1/events
  - https://hallcountylibrary.libcal.com/rss.php?iid=6354&m=month&cid=18963
  - https://tockify.com/api/feeds/ics/meeplemadness (**do not collect**)
