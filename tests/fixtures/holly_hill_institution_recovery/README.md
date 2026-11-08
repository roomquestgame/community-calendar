# Old Santee Canal Park and Orangeburg YMCA publisher fixtures

Captured from unauthenticated public publisher pages on 2026-11-08. The
`capture_manifest.json` file records original response URLs, UTC capture times,
status, byte counts, SHA-256 hashes, the exact read-only RecDesk display POST,
and hashes of these reduced fixtures. Assertions replay publisher evidence;
adversarial test cases change copies in memory.

## Capture policy

Requests used the declared RoomQuest collector user agent. Columbia YMCA's
`robots.txt` was HTTP 200 and specified `Crawl-delay: 10`; same-host research
requests observed that delay. RecDesk's `robots.txt` was HTTP 404; requests used
the collector's ordinary one-second default pace. Requests had no credentials,
cookies, registration, cart, or waitlist mutations. Redirects were rejected.

The RecDesk POST displays the same public program results as the initial page's
filter JavaScript. The form's initial values and `filterPrograms()` call showed:

```json
{
  "ProgramName": "",
  "Code": "",
  "ProgramNameXS": "",
  "DateRangeSelection": "",
  "DateRangeFrom": "",
  "DateRangeTo": "",
  "ProgramType": "0",
  "Age": "",
  "Facility": "0",
  "Days": "0",
  "Pagination": {"CurrentPageIndex": 1, "LoadMore": false}
}
```

The initial page does not contain `ResultsPerPage`, so JSON serialization omits
the undefined `PageSize`. The response selects 25 results per page and states
`Displaying 1 - 5 of 5`. The initial GET's `No results found` placeholder is
retained separately in `recdesk_index_shell.html`; it is not a completed search.

## Reduction

RecDesk fixtures retain canonical identities, title, program narrative,
registration metadata, public fee restrictions, schedule cells, program-list
availability and paging. Scripts, forms, action attributes, cart controls,
styles, comments and contact-only text were removed. Waitlist button text is
retained as inert text. Public organization footer text remains as a deliberate
location-boundary test. The two facility fixtures establish the reviewed
Oak Room/facility 2 and Canal Room/facility 3 address aliases from each facility's
own address fields.

The RSS retains its channel identity, all ten published items, article identity,
publication dates, categories and complete article evidence. Unused WordPress
metadata, styling and contact-only blocks were removed. The craft detail keeps
its canonical URL, publication time, event-specific `og:image`, title and article
body. The parser does not use the feed favicon or general YMCA branding as
event artwork. No images were downloaded into the fixture set.

## Expected replay

All times below are publisher local time, America/New_York.

| Program | Occurrence | Venue evidence |
| --- | --- | --- |
| Homeschool Day — Native Americans (99) | November 11, 10–11 a.m. | Canal Room, Interpretive Center; full, waitlist available |
| Tinsel Trot (95) | November 21, 5:30–8 p.m. | Explicit park address and onsite race-day registration statement |
| Camp Hall Guided Bird Walk (100) | December 5, 9–11 a.m. | Refuel gas station, 309 Avian Pavilion Ln, Ridgeville; offsite |
| Time for Tots — Holiday Season (101) | December 16, 10–11:30 a.m. | Oak Room, Interpretive Center |
| Time for Tots — Thanksgiving (98) | November 11, 10–11:30 a.m. | Oak Room, Interpretive Center |
| Create with Us! Holiday Craft Event | December 5, 10 a.m.–noon | Orangeburg County YMCA, 2550 St Matthews Rd NE, Orangeburg |

Program fee, age/audience, full/waitlist and public eligibility facts remain in
the records. Coordinates are absent and remain subject to the existing verified
venue process. Camp Hall must never inherit the park's Moncks Corner address.

The YMCA feed also includes Columbia venues, a self-paced swim challenge, older
classes and promotional/reporting posts. None supplies an additional verified
current Orangeburg timed occurrence under this reviewed article format. Those
posts are excluded with explicit reasons or held for an unsupported occurrence
shape; they are not converted into invented sessions.
