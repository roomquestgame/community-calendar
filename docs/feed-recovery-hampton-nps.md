# Hampton registration: retain native NPS coverage

Reviewed November 22, 2026. Registration **445**, originally submitted as
`https://www.nps.gov/hamp/planyourvisit/calendar.htm`, is **excluded from the
recovery CSV**. Existing native NPS coverage is confirmed; this investigation
does not add a parallel HTML source or mark the original registration recovered.
Its unresolved issue is receipt routing and duplicate prevention.

## Public publisher evidence

The original page identifies `calendarOptions.parkCode = "hamp"` and references
`/theme/assets/vendor/nps-calendar/nps-calendar.js`. That module uses the public
service below. No authenticated NPS API or guessed credential was requested.

```text
https://home.nps.gov/common/components/nps/eventcalendar/EventCalendarService.cfc
method=getEvents
dateStart=2026-11-22
dateEnd=2027-01-21
expandRecurring=true
pageSize=50
pageNumber=1
parkCode=hamp
```

`https://home.nps.gov/robots.txt` returned HTTP 200, `text/plain`, and permitted
this path for the collector product. It was fetched and evaluated before the
single bounded service request. The service returned HTTP 200 at
`2026-11-22 12:01:55 GMT`, with a JSON body served as `text/html;charset=UTF-8`.
This is evidence only; no global MIME or transport exception was introduced.

The response contained 34 explicit date records and 133 time slots before the
normal current-time filter. All records belong to Hampton. These counts describe
the publisher snapshot, not newly published EventQuest events.

| Native event UUID | Publisher event | Explicit dates and times | Publisher location |
| --- | --- | --- | --- |
| `7352B05D-D663-E4EF-679882E208748B50` | Mansion Tour | 33 listed dates, November 22–January 17; 10–11 a.m., 11 a.m.–noon, 2–3 p.m., and 3–4 p.m. | Meet guide at ramp behind mansion; event coordinates 39.416370, −76.587426 |
| `22E869D5-DB66-D7A1-F9BEE3BE896035B7` | Holidays at Hampton | December 5, 11 a.m.–5 p.m. | 535 Hampton Lane, Towson, MD 21286; event coordinates 39.416332, −76.587571 |

The original page labels 535 Hampton Lane as its mailing address. The holiday
record independently supplies it as the event location; the mailing footer alone
must not be treated as proof of every event's physical venue. The Mansion Tour
fee fields also conflict with a reservation-fee description, so a new adapter
must not infer that every tour is free.

Captured service-body SHA-256:
`b2a8a841936161a28d44856118f53d9c85c827f8f0f8b4ae84a08c6771947b09`.
Raw service bodies remain temporary investigation evidence. Cookies, credentials,
and transient repository-download tokens are not included here.

## Identity and disposition

The main repository's native NPS provider already uses `source_key=nps_public`,
`provider=nps`, the unchanged event UUID as `provider_event_id`, and an occurrence
key formed from each explicit date, normalized publisher start time, and time
index. For example, the first Mansion Tour on December 5 is
`2026-12-05T10:00AM-0`. Its canonical event link is
`https://www.nps.gov/planyourvisit/event-details.htm?id=<UUID>`.

Coordinated production readback confirmed visible native Mansion Tour rows
through January 17, with `hidden_for_review=false`, `America/New_York`, the native
occurrence identity, and a November 19 last check. The main-repository
`docs/eve-145-description-audit.md` also records the deliberate deactivation of
municipal NPS collection to avoid duplicating the authenticated provider.

An ordinary registered HTML source would introduce a different source identity
for those same events. Keep the native provider authoritative. A future fix may
associate the original receipt with that existing coverage, but must preserve the
native identity and explicit duplicate-prevention policy. No new adapter, source
activation, live recheck, production write, merge, deployment, or workflow
dispatch was performed by this investigation.

The execution environment's direct DNS validation cannot resolve publisher hosts.
Evidence was fetched through its existing HTTPS proxy after robots evaluation,
using the normal 0.1 robots and 0.2 publisher user agents. Production DNS and SSRF
guards remain unchanged.
