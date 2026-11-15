# Raleigh direct performance calendars — 2026-11-15

## Exact source profiles

| Source key | Official calendar | Reviewed venue street |
| --- | --- | --- |
| `lenovo_center_nc` | https://www.lenovocenter.com/events/all | Lenovo Center, 1400 Edwards Mill Road, Raleigh, NC 27607 |
| `martin_marietta_center_nc` | https://www.martinmariettacenter.com/events | Martin Marietta Center for the Performing Arts, 2 East South Street, Raleigh, NC 27601 |
| `raleigh_improv_nc` | https://improv.com/raleigh/calendar/ | Raleigh Improv, 1224 Parkside Main Street, Cary, NC 27519 |
| `koka_booth_amphitheatre_nc` | https://www.boothamphitheatre.com/tickets/ | Koka Booth Amphitheatre, 8003 Regency Parkway, Cary, NC 27518 |

These sources were not registered when reviewed. All four use the existing
HTML intake contract and `America/New_York`. The addresses are the official
calendar/footer or native Event schema addresses. No coordinates are invented.
Improv's organization longitude contains the malformed string
`-78.8911115,20.06`; it is not a usable coordinate and is not repaired by
guessing. Every record follows normal exact-street geocoding.

## Public access and complete manifests

Calendar, script and detail captures used the ordinary production user agent,
`RoomQuestCommunityCalendar/0.2 (+https://roomquestapp.vercel.app/)`, normal
robots checks, bounded GET responses and pacing. Robots and content returned
HTTP 200. The complete detail capture processed Lenovo 29/29 candidate pages,
Martin Marietta 24/24 and Improv 17/17, stopping a publisher if any access
denial had occurred. No identity switch, proxy, browser session, private token
or challenge bypass was used. Research-workspace access does not establish
production Vercel access; a production denial remains a hold.

Lenovo's official `/events/all` page contained 68 cards across its future
calendar. Native month/day/year fields identify 29 candidate detail pages in
the current 60-day interval. Unknown listing dates, such as a rescheduled
headline without a year, are hydrated instead of guessed or dropped.

Martin Marietta's first page advertises 12 events and its actual More Events
button. The published `libs.production.js` implements an ordinary GET to
`/events/events_ajax/{offset}` with `category=0`, `venue=0`, `team=0`, blank
`exclude`, `per_page=12`, and `came_from_page=event-list-page`. The endpoint
returns a JSON string containing the next native cards. Offsets 12 and 24 were
verified with HTTP 200. The first two pages provide 24 in-window candidate
events; every item on the third page starts January 15 or later, beyond the
60-day window. The adapter checks date ordering and duplicate URLs before
accepting that boundary. It does not mistake the first 12 cards for a complete
calendar.

Improv's complete calendar includes native month links with explicit years.
Those links bind December/January card ranges to their actual years. The
calendar exposes 17 candidate artist/event pages, including a January 14
candidate that is filtered by its actual showtime if outside the exact window.
Native percent-encoded punctuation remains in the observed event URLs.
Canonical percent-escape case differences are compared as equivalent URLs;
the exact host and event-route checks remain intact.

Koka's tickets page contains two calendar placeholders for the same festival
and a later Tom Segura event. The festival placeholders link to the official
https://www.boothamphitheatre.com/nc-chinese-lantern-festival/ overview. That
page, rather than its midnight calendar range, supplies the real schedule.
The later concert detail was read and correctly falls outside this snapshot.

## Event narratives and occurrence rules

Lenovo and Martin Marietta preserve the complete `.event_description` body.
Every dated `.showings_date` plus `.time.cell` pair creates one occurrence;
multi-day listing ranges never generate arbitrary daily shows. Lenovo's
ticket labels or explicit listing year bind showings whose display omits a
year. Native weekday contradictions are held. Door times are not substituted
for the actual show clock, and unpublished ends remain null. Martin Marietta's
native auditorium/theatre name is retained in `venue_room` evidence while
using the center's verified common street address.

The full Lenovo capture found 20 game pages whose entire description block
only directs readers to `CarolinaHurricanes.com` or `GoPack.com`. Those generic
homepage links do not constitute event narratives and are held under the
full-description requirement. Pentatonix's native description is also empty.
Martin Marietta's TYM Fall Orchestra Concert has no native description and is
held. No title, team name or generated prose substitutes for those bodies.

Improv's JSON-LD provides every showtime and the exact venue address. Its
generic short schema description is not used; the whole `.bio-text` supplies
the native narrative. A comic page can include a separately named engagement:
Red Grant's page also lists his New Year's Eve performances. The collector
binds each calendar packet to its own explicit date range and declared show
count, preserving the holiday engagement through its own calendar card and
avoiding duplicate or incorrectly titled occurrences.

Koka's official festival overview states November 21, 2026 through January 10,
2027, daily 6–10 PM, with Christmas Day closed. Thanksgiving and Christmas Eve
have 6–9 PM gates and no Twilight Session; New Year's Eve/Day use normal hours.
Those explicit rules yield 50 regular evening occurrences. Ticket admission
options are not treated as additional independent performances. The complete
official overview and ticket/session narratives are preserved, together with
the complete Holiday Hours answer. The separately labeled long venue FAQ is
outside the event description. The accepted narrative is 2,795 characters;
it is not clipped from the page's 17,000-character combined FAQ/content text.

## Durable completion and limits

The adapter has two checkpoint phases. During `phase='listing'`, page discovery
continues and `listing_complete=false`; `cursor=0` is not a completed snapshot,
even if an accumulated queue is temporarily empty. After the complete manifest
is established, `phase='details'`, `listing_complete=true`, and `queue` contains
every normalized native detail packet. Only `cursor == manifest_count ==
len(queue)` in this final phase permits staging.

The immutable `started_at` anchors the 60-day window. Checkpoints expire after
four hours, are hashed and validated before resume, and are bounded to 850,000
stored bytes. Each source exposes explicit 200-manifest and 200-event capacity
maps. Ten fetches per call and the worker deadline bound processing. Every
resume continues from the accepted detail cursor without refetching the prefix.
No incomplete call returns events. Overflow or changed native structure fails
visibly rather than truncating the calendar. Descriptions over 12,000
characters are held rather than clipped.

## Complete captured-payload replay

These are offline verification results at a 2026-11-15 12:00 UTC anchor, not a
claim of production publication. Replay used four fetches per call to exercise
resumes more frequently than the production ten-fetch budget.

| Source | Accepted occurrences | Held detail pages | Manifest details | Requests | Replay chunks |
| --- | ---: | ---: | ---: | ---: | ---: |
| Lenovo Center | 17 | 21 | 29 | 30 | 8 |
| Martin Marietta Center | 65 | 1 | 24 | 27 | 7 |
| Raleigh Improv | 32 | 0 | 17 | 18 | 5 |
| Koka Booth Amphitheatre | 50 | 0 | 2 | 3 | 1 |

All accepted rows retain full native descriptions and complete reviewed street
addresses. Every normalized `(id, starts_at)` is unique, all local-to-UTC
conversions preserve the publisher's clock, and every resumed request URL was
fetched exactly once. All checkpoints remain below 850 KB. Focused tests cover
actual showing dates, omitted years, weekday conflicts, no invented ends,
complete biographies, canonical URL equivalence, named holiday engagements,
festival exceptions, generic-link holds, listing-phase 0/0, complete-only
resumes, changed pages, checksum/scope validation and visible record limits.
