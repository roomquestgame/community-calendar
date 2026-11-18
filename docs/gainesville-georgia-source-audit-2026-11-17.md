# Gainesville, Georgia — primary-source calendar batch (2026-11-17)

This batch implements **new** first-party publisher calendars only. Existing Ticketmaster, Localist and iCalendar providers and their live listings are untouched. No database migration, production source approval, schedules or geocoder retries are initiated by this collector PR. Each record is one real occurrence with its own title, date, publisher link and street; the existing EventQuest backend owns verified coordinates, category classification, media publication rights and duplicate suppression.

## Direct-source collector audit

| Publisher | Public publisher endpoint | Adapter | Future event records in bounded dry run | Text/venue/image evidence | Status |
|---|---|---|---:|---|---|
| Explore Gainesville | `https://www.exploregainesville.org/wp-json/tribe/events/v1/events` | WordPress Tribe Events REST JSON, one-page 30-day window | **35** accepted of **43** returned | 35 complete sanitized descriptions (146–2,084 chars); 35 event-specific street addresses; 29 image candidates; 0 publisher coordinates, requiring existing geocoder | Ready for backend registration and geocoding; not yet published |
| Blackstrap Rock Hall | `https://www.blackstraprockhall.com/events?format=json` | Squarespace public JSON | **7** accepted of **8** returned | 7 sanitized descriptions, 7 verified street-address records, 7 publisher-provided coordinates, 7 image candidates | Ready for backend registration; not yet published |
| The Arts Council | `https://www.theartscouncil.net/events?format=json` | Squarespace public JSON | **0** | 12 total upcoming in endpoint, largely beyond the 30-day horizon; near-term items lack event-level verified street addresses | Parser installed for future use, **no production source enrollment** until precise locations and near-term schedule are verified |

Counts observed November 17–18, 2026, during actual collector dry runs with publisher robots and bounded fetching. Counts are **not** production event counts and may change on subsequent refreshes.

### Technical blocks, ambiguous calendars, and excluded candidates

| Source | Outcome | Action |
|---|---|---|
| Brenau University | Events Calendar REST endpoint HTTP 403 | No circumvention; skip/hold |
| Greater Hall Chamber | Chamber events host HTTP 403 | No circumvention; skip/hold |
| NoFo Brew Co. Gainesville | Official venue page HTTP 403 during fetch test | No circumvention; skip/hold |
| Hall County Library System | Public LibCal monthly RSS `?iid=6354&m=month&cid=-1` returns 0 entries; other API requires credentials/403 | Alternate publisher feed needs review |
| Elachee Nature Science Center | Public calendar landing page responds, but no reviewed structured endpoint and event-level data validated | Discovery only, skip automated import |
| Historic/seasonal farmers markets and undated recurring claims | No eligible dated upcoming occurrence confirmed | Do not fabricate an event |

### Admission and release safeguards

- The registry source key, exact endpoint, adapter, host allowlist, publisher link path, timezone `America/New_York`, description length and event-specific street are validated. Missing or nonpublic events are held, never pinned to a city/tourism centroid.
- WordPress API pagination is bounded, with the 30-day window deliberately keeping Explore Gainesville to **one page**; its `robots.txt` requires a **30-second crawl delay**, so fetching a second page in a 60-second function would violate the publisher's admission budget.
- HTML is sanitized and character entities decoded. Unknown URLs, low-resolution image names, logos and mismatched publisher hosts are rejected. Image candidates are **not licensing grants**; backend media stages must enforce publisher rights and valid full-resolution reachability before display.
- Source category and event category must be assigned by the canonical EventQuest classifier from individual event categories, titles, descriptions and actual venue identity. Ambiguity is held for review instead of being pushed into “Other”.
- No broad scheduled GitHub Actions job; use existing bounded Vercel collection, staged events, existing geocoder, existing source-level audit and normal Events/Map/Home discovery. No new app UI or database schema.
- No publisher's event content or image is published by this PR alone. Production enablement requires independently verified backend source registration, source permissions, geocoding, deduplication and live cards.

### Test evidence

`python -m unittest discover -s tests -p 'test_gainesville_sources.py' -v`: **7 passed**. Covers exact source identity, sanitized long narratives, no fake street/coordinates, Squarespace fallback narrative, empty descriptions, thumbnail/logo rejection, WordPress page and occurrence identities. Dry runs used the actual `preview_source` entrypoint, not a separate mock collector.

## Follow-on

One separately reviewed Gainesville backend migration PR may register **both verified sources together** and expand any confirmed missing classification triggers. This collector PR intentionally ships no SQL to protect the completed PostgreSQL 17 squash baseline and unrelated migrations.
