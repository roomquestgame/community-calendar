# Dose Yoga Raleigh public calendar

The new source is `dose_yoga_raleigh_nc`, with the exact HTML tuple `https://www.doseyogastudios.com/events-list`, `html`, `html`, `America/New_York`.

The official calendar and its two studio pages returned HTTP 200 under the unchanged guarded research fetcher, with the honest RoomQuestCommunityCalendar user agent. Its robots file returned HTTP 200 and permitted these reads. The three selected event details also returned HTTP 200. These research observations do not establish future production access or publisher licensing permission.

## Complete calendar discovery

The [native event calendar](https://www.doseyogastudios.com/events-list) contains seven cards in one Webflow collection, with no pagination controls. The complete Raleigh scope accounts for every card: three eligible Raleigh programs, three explicitly Durham-only programs outside this source's geography, and one dated program that ended before the frozen window. The parser inspects all cards and fails visibly if pagination appears or the collection shape changes. Future generic titles are inspected rather than silently discarded; an unresolved venue or schedule is held with a reason.

The frozen anchor is **2026-11-15 13:45 UTC**. The rolling local-date window is November 15 through January 13 inclusive. Six unique native pages are read: calendar, both studio address pages and all three eligible details. The collector uses at most three fetches per chunk and releases events only after complete listing, venue and detail accounting.

| Native program | Occurrences in this window | Explicit timing | Venue |
|---|---:|---|---|
| [Raleigh Walk Club](https://www.doseyogastudios.com/events/dose-walk-club-raleigh) | 8 | Thursdays, 7:00 a.m. stretch; 7:15 walk; optional café gathering until 8:30 a.m. | Dose Downtown Raleigh |
| [Raleigh Book Club](https://www.doseyogastudios.com/events/dose-raleigh-book-club) | 1 | November 19, 6 p.m.; end unstated | Sixty Vines, North Hills |
| [North Hills Kirtan](https://www.doseyogastudios.com/events/community-kirtan-noelle-whittington-north-hills) | 1 | December 9, 7:30 p.m.; end unstated | Dose North Hills Raleigh |

The walk retains the explicitly invited stretch-through-café period, 7–8:30 a.m. It does not derive an end from approximate walking duration. Its weekly label and detailed clock both must be present. A stated launch date is respected; when the launch omits its year, only one weekday-consistent candidate among the anchor's year and adjacent years is accepted. Explicit named month/day closure lists are honored. Unknown holiday labels, conditional closures, date ranges or weekday contradictions hold the recurring program. No holiday closures were stated in the captured program. A monthly book-club description does not create unannounced monthly dates.

The two one-off visible dates and clocks must independently agree with their Event JSON-LD starts. Their ends stay absent. Event page title, JSON-LD title and exact same-host URL must agree before prose or a location can be used.

## Three exact venue addresses

| Named event venue | Stored street | Primary evidence |
|---|---|---|
| Dose Downtown Raleigh | 415 N Harrington St, Raleigh, NC 27603 | [Publisher studio page](https://www.doseyogastudios.com/location/downtown-raleigh) |
| Dose North Hills Raleigh | 540 St. Albans Drive Suite 100, Raleigh, NC 27609 | [Publisher studio page](https://www.doseyogastudios.com/location/north-hills) supplies Suite 100; [North Hills landlord directory](https://www.visitnorthhills.com/directory/dose-yoga) supplies the complete street |
| Sixty Vines, North Hills | 4000 Center at North Hills Street Suite 110, Raleigh, NC 27609 | [Official restaurant page](https://www.sixtyvines.com/locations/raleigh-nc) supplies Suite 110; [North Hills landlord directory](https://www.visitnorthhills.com/directory/sixty-vines) supplies the street suffix |

The book club explicitly names the offsite restaurant. Neither Dose studio is used as its fallback. The North Hills studio page omits the street suffix, and its footer's Maps query says “St”; the separately verified landlord address supplies “Drive.” Parking-garage addresses are never used as event locations. These exact event-name/venue bindings were reviewed by the parent using the primary pages. The native studio pages are revalidated during collection; a changed suite or venue page holds the capture for review.

No native event points were present in the six captured pages. All ten records retain null coordinates and enter the ordinary address geocoder. A source coverage center or studio default never supplies a point. If a future matched Event object supplies a complete plausible native coordinate pair, that pair retains separate publisher-event provenance.

## Complete prose and images

The adapter extracts the complete event content column, including introductory text, performer credit, rich-text program body and any native pricing list. Navigation, duplicate structured date/location metadata and empty pricing labels are removed. The Event JSON-LD description is not substituted for the full visible body; the book club's structured description is empty while its visible prose is complete.

Frozen normalized descriptions contain 541 characters for each walk, 516 for the book club and 1,300 for Kirtan. The parser requests a sentinel beyond 12,000 characters and fails on overflow; it never silently slices a long body to the publication limit. The matched native Event image URLs are retained from Dose's fixed Webflow asset namespace.

Full publisher narratives remain in temporary capture/replay files only, not this repository evidence document or synthetic tests.

## Checkpoint contract and local verification

The source uses `dose_v1`, version 1, with manifest limit 100, event limit 300 and maximum checkpoint size 850,000 bytes. Complete proof requires all three fixed seed pages, an empty pending-page list, both native studio proofs, and `cursor = manifest_count = queue length = outcome length`. Total cards must equal detail entries plus explicitly counted geography/window exclusions. Every detail outcome binds the native item to its emitted record hashes or held reason. Resumed records retain exact event URL, title, stable occurrence identity, approved street/provenance and full text integrity.

The complete frozen capture produces **10 events**, no held eligible details, in **two chunks**. The checkpoint is about 20 KB. The focused suite covers incomplete/complete proof, source and page identity, rolling weekdays and DST, launch boundaries and closure exceptions, concrete date/time conflicts, offsite venue and suite preservation, long-body integrity, native-only points and refusal to silently stop at a first pagination page. No classifiers, dedupe rules, shared transport policy, production source or workflow was modified by this module.

## Other discovery outcomes

The roster check excluded Raleigh City Farm because source 5128 is already healthy. Triangle Land Conservancy has two existing held registrations; research stopped after its landing-page access check, without feed/API/detail requests. Dose was the only source selected from this discovery pass. Dix Park, Activate Good and Raleigh Parks landing pages were accessible but unselected; no complete calendar capture or production access claim was made for them. Previously held publishers in the parent exclusion list were not retried.
