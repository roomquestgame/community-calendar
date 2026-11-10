# Source fixture provenance

`shady_events.html` is a formatted copy of the event container DOM observed in
the ordinary public browser page on 2026-11-10:
https://shadyshackgrill.com/bracey-shady-shack-bar-and-grill-events

The live page exposed eight `.events-holder > section` cards under
`main#content > article > .pagecontent > .container`. Each card had its own
numeric section ID, matching `data-event-id`, title, visible month/day,
explicit AM/PM time range, `.event-info-text`, and SpotApps event image.
The year was absent from each visible date. Tests modify this captured
structure to exercise explicit years, rollover, safety and lifecycle cases;
those modified scenarios are synthetic, not additional publisher events.

The source owner's instruction in this task authorizes using the venue's
current year for a yearless month/day. When the normal 60-day collection window
crosses New Year, an early-year date inside that window is assigned to the next
year. Past dates outside that window are excluded. An explicit date year takes
precedence, including old flyer dates, and is never advanced to a newer year.
Only the listed occurrence is collected; `Every Thursday`/`Every Sunday`
does not authorize recurrence expansion. Assumptions appear in collector
diagnostics, not publisher-authored facts or event descriptions. IDs combine
the publisher's numeric occurrence ID and resolved local date, and remain
stable across repeated fetches of that same occurrence.

The official homepage confirms the venue address as 183 Hendricks Mill Road,
Bracey, VA 23919: https://shadyshackgrill.com/

Browser access and this fixture establish DOM shape, not publisher permission
or transport readiness. This workspace's normal collector guard returned
`dns_unavailable` before HTTP. A network-capable run through unchanged DNS,
robots, host, deadline and response guards is still required before activation.
