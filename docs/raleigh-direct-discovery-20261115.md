# Raleigh primary-calendar expansion — discovery and release scope

## Scope

The November 15 review compared publisher leads against the actual regional
source registry before implementation. The inventory contained 97 municipal
source records, including 44 healthy active sources, 17 active empty sources
and 36 held or unreviewed records. NC State and DNCR also have separate active
Localist execution paths. Working published sources were excluded from this
release; the one repair reuses the existing paused Natural Sciences identity.

The previously captured Visit Raleigh directory was useful for venue discovery:
3,669 dated rows represented 1,217 listings and hundreds of venue/organizer
groups. Its production source remains paused after HTTP 403, with no imports.
This release collects independent primary publisher pages and publicly exposed
feeds. It does not enable, retry or route around the blocked aggregator.

## Twenty reviewed integrations

| Category | New or repaired primary calendars | Native feed or schedule |
| --- | --- | --- |
| Nightlife and social | Neptunes; Tin Roof; Slim's; Sports & Social Cary; Cannonball Music Hall; Goodnights; Raleigh Improv | Squarespace JSON, Gigwell, Tribe REST, Humanitix and native show details; full prose and explicit occurrences |
| Arts, culture and education | Natural Sciences repair; Artspace; Raleigh Little Theatre; Martin Marietta Center | Public APIs, exact month renderer, complete show details and explicit performance schedules |
| Outdoor and active | Downtown Cary Park; Triangle Rock Club Salvage Yard Run Club; Natural Sciences' Prairie Ridge programs | Both park feeds plus detail pages; publisher-declared weekly run schedule; event-specific native venues |
| Food and drink | Hone-Sharpen; Transfer Co. Food Hall; Our Giving Kitchen Raleigh | Public cooking classes, food-hall events and volunteer cooking sessions with complete detail narratives |
| Family and kids | Natural Sciences; Downtown Cary Park; Raleigh Little Theatre; Koka Booth festival; fairgrounds | Science programs, workshops, storytimes, explicitly timed festival nights and seasonal events |
| Sports and fitness | Triangle Rock Club Run Club; usable Lenovo Center events; relevant park programs | Explicit local schedule and actual detail showtimes; generic team-link-only pages are held |
| Markets, makers and shopping | N.C. State Fairgrounds / Raleigh Market; Cary Farmers Market through the park feed; Artspace | Monthly dated market schedule, primary-organizer street resolution and arts workshops |
| Gaming and hobbies | Game Theory Raleigh | Official public embedded event data, restricted to its Raleigh store; blank native descriptions are held |
| Civic, volunteering and community | Our Giving Kitchen; Downtown Cary Park; fairgrounds; museum programs | Public volunteer sessions and community calendars with actual venues |
| Aggregator discovery | Existing captured Visit Raleigh directory, cross-checked against primary sites and the source registry | Discovery only; production HTTP 403 hold retained |

The twenty unique source keys are defined in `raleigh_direct_sources.adapters()`
and the exact tuples in the five adapter modules. They consist of nineteen new
registrations plus the guarded repair of source134. Existing healthy university,
museum, library, civic and other regional sources are not included as new work.

## Disabled candidates registered with the release

| Candidate | Primary page | Specific reason |
| --- | --- | --- |
| Craft Habit | https://www.crafthabitraleigh.com/classes--events-calendar.htm | Robots HTTP403; no calendar request followed |
| Marbles Kids Museum | https://www.marbleskidsmuseum.org/ | Robots HTTP403; no calendar request followed |
| Theatre Raleigh | https://www.theatreraleigh.com/events | Its authoritative ticket calendar's robots returned403; production ranges alone do not provide showtimes |
| LGBT Center of Raleigh | https://www.lgbtcenterofraleigh.com/calendar | Official embedded Google calendar feed is robots-disallowed; feed body not fetched |
| Wolfe & Porter | https://www.wolfeandporter.com/events | Official embedded Google calendar feed is robots-disallowed; feed body not fetched |
| Crank Arm Brewing | https://crankarmbrewing.com/events/ | Robots endpoint returned202 instead of a usable policy; collection stopped |
| Bond Brothers Eastside | https://www.bondbrothersbeer.com/calendar | Automatic approval review rejected the proposed Elfsight access-path adjustment; no endpoint content was fetched after rejection |
| Fortnight Brewing | https://www.fortnightbrewing.com/event-calendar/ | Both public calendar displays returned200, but future event entries lack full descriptions |

These reasons are deliberately distinct. A content gap or an approval-review
rejection is not labeled an HTTP403. Disabled entries receive no worker demand,
checkpoint profile or publication request. Any newly enabled source that returns
403 or robots denial from production follows the ordinary permanent-failure
path into paused/disabled status, without alternate identities or retries.

## Discovery leads without a verified complete feed

These remain research leads, not enabled integrations or claimed ingestion:

| Lead | Observed page | Remaining evidence gap |
| --- | --- | --- |
| ComedyWorx | https://www.comedyworx.com/upcoming-shows and https://www.comedyworx.com/calendar | Full public detail prose exists, but the upcoming list reports more pages and the calendar snapshot covers only its displayed month range. The advertised event sitemap also mixes 2,349 historical URLs, including240 undated slugs. No partial first page is certified as a complete60-day calendar. |
| Chapel of Bones | https://chapelofbones.com/events/ | Official TickPick organizer widget identified; complete public data/pagination contract remains unverified |
| Crooked Hammock Raleigh | https://www.crookedhammockbrewery.com/locations/raleigh/events | Public Popmenu page is a calendar shell; no complete event payload or verified Raleigh street in the captured response |
| ShopSpace | https://www.shopspace.org/classes | Public Bookeo calendar widget identified; complete anonymous event-feed contract remains unverified |
| NOCO | Primary research request | Research timeout, not a403 or robots denial; no ingestion eligibility claimed |
| JC Raulston Arboretum | https://jcra.ncsu.edu/events/calendar/index.php | Separate native calendar identified, but active NC State Localist already supplies arboretum programs. A dedicated source needs a demonstrated coverage gap and duplicate review before enrollment. |

These leads are retained to make the discovery work reviewable. They are not
counted among the twenty integrations or the eight newly registered disabled
candidates. No speculative API route, inferred monthly performance series or
city-center address is published to fill a missing feed contract.

## Release verification

The collector and backend changes are consolidated by repository, rather than
one PR or deployment run per venue. The release uses the existing HTML category
worker, preview-v2 staging, geocoder, shared classifier and publication path.
Each complete capture must retain every accepted native description and full
street. Missing/ambiguous content remains a per-event diagnostic.

Independent review found and corrected a completion gap before release: an
unfinished listing can have an empty0/0 detail manifest. Both worker and database
now require source-specific listing and detail completion before staging or
successful preview recording. Real captured records are reconciled through the
actual local database functions, not a parser-only approximation. Production
release receipts separately record deployment SHAs, migration history, source
outcomes and actual staged/published description/address reconciliation.

Detailed implementation evidence is in the accompanying arts, community,
nightlife and performance documents. Temporary complete publisher captures are
used for validation and are not committed as scraped-page archives.
