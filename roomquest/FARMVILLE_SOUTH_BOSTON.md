# Farmville and South Boston source batch

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
