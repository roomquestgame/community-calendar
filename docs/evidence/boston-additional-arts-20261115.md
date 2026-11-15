# Boston additional arts and family sources — November 15, 2026 UTC

Prepared from the previously unfinished Boston batch. These counts describe captured native events and successful local worker/adapter replay. Production publication is verified separately by the coordinated backend release.

| Source | Captured events | Missing descriptions | Missing streets | Needs geocoding |
| --- | ---: | ---: | ---: | ---: |
| Museum of Science, Boston | 5 | 0 | 0 | 5 |
| Coolidge Corner Theatre | 179 | 0 | 0 | 179 |
| Brookline Arts Center | 9 | 0 | 0 | 9 |
| Eliot School of Fine & Applied Arts | 24 | 0 | 0 | 24 |
| Harvard Museums of Science & Culture | 5 | 0 | 0 | 5 |
| Peabody Essex Museum | 56 | 0 | 0 | 0 |
| deCordova Sculpture Park and Museum | 7 | 0 | 0 | 7 |
| New England Aquarium | 0 | 0 | 0 | 0 |

Total: **285** explicit native occurrences. All 17 focused regression tests passed. The real category worker replayed every captured native row through checkpoint, staging, completion and publication boundaries using simulated RPC responses. Every incomplete checkpoint returned an empty events list and made no staging or publication call. Native source descriptions are retained in full, with hashes and lengths in the JSON receipt.

## Source-specific corrections

- Coolidge accepts exact native individual-ticket IDs and course-bundle GUIDs, with a stable ID for each dated session. It traverses the native month pagination and coming-soon list, then retains only actual future showtimes.
- Museum of Science preserves the complete event narrative and speaker biographies, parses explicit multiple sessions, and keeps the available midday Cody Rigsby family session while withholding the sold-out evening session.
- Eliot traverses every native month and overflow-day page. Its offsite sharpening class resolves to Boston Building Resources at 100 Terrace Street, Boston, MA 02120.
- PEM accepts both native HTML/JSON-LD and canonical Markdown with embedded ICS. It removes aggregate series envelopes when individual sessions are available, including after the first session expires. Its native exact museum point is retained.
- deCordova verifies the canonical event URL and title while normalizing only dash typography, preserves full prose, and separates explicitly labeled family/adult yoga sessions.
- Museum of Science and deCordova validate native row totals across listing pages and reject repeated IDs or changed totals before any events are staged.
- Aquarium follows native availability pagination and binds availability to the exact program title and date. It uses complete TEC REST totals and strict-public canceled, postponed, hidden, virtual and member-only exclusions. Its current three native records are ineligible: one sold-out public event and two member-only mornings.

## Remaining publisher data condition

One Brookline Arts Center workshop is held because its native weekday and calendar date disagree (Tuesday versus December 10, 2026, which is Thursday). No date is invented. All other holds in the receipt are ended events, events outside the 60-day window, virtual/member-only entries, or film programs without a currently eligible native showtime.

## Production boundary

Local capture respected publisher robots and pacing, including Eliot’s 10-second delay. The actual worker replay uses cached native responses and simulated RPCs, so it does not prove guarded production transport or live publication. Normal production workers must independently collect and geocode the exact streets; the coordinated release performs the staging-to-public narrative and address comparison. No synthetic demand, alternate venue pins, or public production writes were performed by this subtask.
