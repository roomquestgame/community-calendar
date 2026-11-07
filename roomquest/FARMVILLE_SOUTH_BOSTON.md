# Farmville and South Boston source batch

## Basketball and workshop review

The Joan Perry Brock Center's WordPress calendar replayed 13 upcoming Longwood
home games with explicit times and its documented arena address. The collector
checks venue ID, home matchup, public status and agreement between local and UTC
times. SOVA's public program page replayed two in-person AI workshop sessions
with start and end times at its South Boston address. Collect only sessions
that explicitly name that location.

Farmville Chamber has no qualifying records in the reviewed window. Longwood
campus and visual arts still need usable public occurrences. Hampden-Sydney's
public music series has no upcoming date and time, and its main calendar mixes
audiences. North Street's sitemap includes historic Wix details and does not
establish the complete current schedule. The Waterworks ticket route redirected
in guarded transport.

## Pending-route activation review

The official Halifax County Chamber XML returned two explicit public tour
occurrences. The XML route requires chamber ID 845 and excludes any listing
carrying a member or internal visibility flag. Farmville Chamber's XML had no
qualifying public records in the normal window.

The Speedway pairs individually linked race details with the current season
calendar and verifies the local green-flag time and track address. Discover
Halifax verifies the advertised listing count, then checks all available event
details in a seven-day window, bounded at 18 requests. The Woodbine Christmas
Market occurrence stays held on conflicting published times. These routes
require a successful guarded publisher audit before approval.

## Follow-up intake

The follow-up audit includes all 15 original routes plus the official Waterworks
Players ticket catalogue and the Red Door 104 workshop catalogue. Use the
existing `farmville_south_boston_live` workflow input. A publisher response
alone does not qualify a source for activation.

| Source | Follow-up evidence and release condition |
| -- | -- |
| Farmville Parks & Recreation | Production collected and published three events. Indoor Walking and Senior Holiday Bingo need classifier review. |
| Visit Farmville | Production published four markets. The Hamilton screening is held on a geocoder match. The exact library address and marker are on the publisher's location page. |
| Berry Hill Resort | Production staged six events; its exact resort address needs a verified marker before the normal publisher resumes. |
| Halifax County government | Production paused on `robots_unavailable`. Review publisher access before an explicit reactivation. |
| Discover Halifax | Directorist listing exposes dated cards and detail fields; reconcile advertised count, detail budget, street address formats and source overlap before enabling. Hold the Woodbine Christmas Market occurrence with conflicting published start times. |
| Halifax County Chamber | Event details expose structured starts and ends. Verify complete listing retrieval and physical locations before selecting an HTML or ChamberMaster route. |
| North Street Press Club | Exact Wix details parse. The public catalogue still exposes Load More and recurring occurrences. |
| The Prizery | HTML collector supports individually timed shows and an explicitly timed reception. Date ranges alone do not establish showtimes. Use production transport validation before activating the route. |
| Farmville Area Chamber | Publisher disallows the previously tested search route; review the public upcoming-events listing and exact detail URLs. |
| Longwood campus | Public eligibility, stable endpoints and event venue resolution need verification. |
| Longwood Center for the Visual Arts | Exhibition ranges need specific public hours or timed openings. |
| Hampden-Sydney College | RSS includes mixed audiences; identify public events and exact campus venues. |
| Longwood basketball | Respect the publisher pacing result and identify home game dates, times and venue. |
| South Boston Speedway | Official dated schedules exist. Confirm upcoming race details, including weather rescheduling semantics. |
| SOVA Innovation Hub | The Atom feed timestamps need to be corroborated with occurrence starts and physical locations. |
| Waterworks Players | The official ticket page links Ludus; the ticket catalogue returned HTTP 403 during research. A dated public route is required. |
| Red Door 104 | The official workshop catalogue has dated products. Check detail-level start times, year, availability and duplicate Visit Farmville listings. |

Mecklenburg County YMCA already has an approved public-programs route. The
six current staged programs are in Clarksville. Chase City branch programs
need qualifying occurrence evidence before adding a separate route.

One batch covers all 15 candidates. The table records the intake decision for
each source. Candidate counts come from publisher payload replay on November 7,
2026. Database registration, production transport validation, and publication
under genuine search demand are still pending.

| Source | Evidence and remaining gate |
| -- | -- |
| Farmville Parks & Recreation | Shared iCalendar parser yielded three timed records at the Sports Arena. Check the production transport and register with the existing iCalendar route. |
| Visit Farmville | The HTML parser paired dated calendar rows with individual venues, descriptions, categories and original artwork. Five current occurrences replayed, including four market dates and the Hamilton screening. |
| Farmville Area Chamber | Upcoming-events page has dated events. Robots disallows the tested calendar search endpoint. Find an approved route with complete individual times and venues. |
| Longwood campus | LiveWhale identified in the publisher page. The bounded public JSON request timed out. A public audience filter and usable venues still need verification. |
| Longwood Center for the Visual Arts | Publisher detail and exhibition metadata found. Sample Events Calendar API returned zero events. Exhibition date ranges need appropriate hours and recurrence evidence. |
| Hampden-Sydney College | Public EMS RSS returned 104 items, including theater and tutoring. The feed mixes audiences and gives room labels without street addresses. Confirm public eligibility and locations. |
| Longwood basketball | Official schedule exists. Advertised publisher pacing exceeded the local audit deadline. Confirm a route that respects it and selects home games. |
| North Street Press Club | Individual Wix event pages parse, including the November 11 open mic. The public list exposes a Load More button, so the full-snapshot parser holds it before reading event details. |
| Discover Halifax | Calendar exposed 72 links, with Woodbine event date, venue and time in individual details. The reviewed WordPress record omits the date and venue fields. Confirm bounded coverage before onboarding. Christmas Market start times differ across publishers. |
| Halifax County Chamber | The community calendar exposed 100 links. The linked iCalendar sample redirected. Verify the destination and event facts before enabling collection. |
| The Prizery | Theater and music detail pages loaded. Performance ranges need dated ticket sessions for each showtime. |
| South Boston Speedway | Official 2026 schedule and 2027 announcement exist. Test dated race and time extraction, including postponements. |
| SOVA Innovation Hub | Public Atom feed returned 10 entries. Event detail response has navigation without time or venue fields. Verify the Atom timestamp semantics, actual venue, and deduplication with Clarksville ChamberMate. |
| Berry Hill Resort | All seven advertised detail pages captured. Six in-window records replayed with venue evidence and publisher artwork candidates. One later event fell outside the worker window. |
| Halifax County government | Shared iCalendar parser yielded seven timed civic events and skipped six all-day closure notices. Confirm civic coverage and registration. |

Visit Farmville and the reviewed Wix calendars use the existing HTML worker and
publisher evidence interface. The worker binds URLs to the enrolled publisher,
checks robots and pacing, and rejects unknown or incomplete schedules. Wix
detail pages supply the venue and time. Visit Farmville uses the listing for
each dated occurrence and checks it against the detail schedule before using the
detail's venue. Event locations use the shared geocoder. Images are candidates
for the existing image verification worker.

Run the full read-only batch through the `farmville_south_boston_live` input of
RoomQuest Provider Tests. The runner uses the shared production transport and
prints counts and bounded failure codes. A payload-only result establishes
access and leaves adapter readiness open. Before activation, pair the collector
with a tested backend registration, run the standard release checks and verify
public records under real area demand.
