# Holly Hill institution fixtures

Captured from public publisher pages on November 8, 2026 UTC. These are parser
fixtures, not evidence of a deployed collector run or source activation.

| File | Publisher URL | Scope |
| --- | --- | --- |
| `st_george.ics` | `https://dorchesterlibrarysc.libcal.com/ical_subscribe.php?src=p&cid=22342` | Five original components: three timed programs and two dated closures. |
| `moncks_corner.ics` | `https://berkeleylibrarysc.libcal.com/ical_subscribe.php?src=p&cid=8209` | Four original components: two branch programs, the off-site Trident career fair, and a date-only Cypress Gardens notice. |
| `octech_browse.html` | `https://octech.coursestorm.com/browse` | Original eight-card first page, sorted by next session, with pagination. |
| `defensive-driving17.html` | `https://octech.coursestorm.com/course/defensive-driving17` | Original November 10–12 course; its visible Tuesday/Thursday 6–10 p.m. sessions and JSON-LD are retained. |
| `cane_bay_events.html` | `https://ymcagc.org/events/` | Original four dated cards, October 17 through November 6, 2026. No later recurrence was generated. |

Sanitization removed library organizer/contact/attendee fields, decorative
images and maps (including embedded map API parameters), executable scripts,
styles, password/hidden inputs, and generated element identifiers. OCTech's
Event JSON-LD remains. Event titles, UIDs, dates, descriptions, locations, prices,
and event links were not rewritten. Tests explicitly make adversarial or
hypothetical changes in memory; those variants are not publisher evidence.

The December 8 course detail, `/course/defensive-driving18`, returned an empty
response on two ordinary HTTPS attempts; the final attempt was HTTP 202 with
zero bytes. No synthetic December detail fixture was created. The collection
test verifies that an empty required detail fails the source rather than
claiming a complete, healthy partial catalog.

The shared production fetcher was also attempted here, with robots enabled and
exact allowed hosts, but this runtime could not resolve publisher DNS through
its direct DNS guard. Fixtures were subsequently captured using ordinary public
HTTPS, without authentication, cookies, challenge-solving, or alternate hosts.
The implementation itself only uses the shared fetch callback; it contains no
transport replacement. Deployed guarded-fetch validation remains required.
