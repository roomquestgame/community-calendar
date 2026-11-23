# National protocol and regional Wildlife fixtures

These are synthetic records using publisher field structures inspected on
22 November2026; they do not copy complete publisher event narratives.

Wildlife structure was verified against the BCN `/events/rss.xml` feed and
`/events/2026-11-23-nature-journaling-sharon-williamson-paxton-pits` detail.
Drupal supplies Event microdata, separate event date/time fields, an event Place,
native point/address, event summary/about and a dedicated hero image. RSS
`pubDate` uses a date or date range at synthetic noon, not the event clock.

OpenActive fixtures follow Better's public `session-series` and
`scheduled-sessions` feeds. Its parent contains descriptions and venues while
the scheduled occurrence references the parent's native identity and supplies
its own date/time/status. Both feeds use RPDE items/next/license, including
updates and tombstones. Bookwhen uses the same separate-stream shape; its
PartialSchedule must never be extrapolated. Tests synthesize pagination tails,
outages, late deletion, cursor escapes and transactional replay explicitly.

## Published Wildlife clock syntax

`wildlife-published-clocks.json` preserves the exact visible `Time` strings
from two official Lincolnshire event pages inspected on 23 November 2026:
`1pm to 3.30pm` and `1.30pm to 2.30pm`. The source URLs and visible dates are
recorded alongside them. Tests insert those strings into the existing
synthetic Drupal fixture; the fixture's venue remains synthetic test data.

The expected datetimes are explicit test controls derived from the visible
date and time, not a fresh capture of the publisher's hidden datetime
attributes. The web extraction did not expose raw attributes, and the local
guarded network reader could not resolve the publisher. This fixture proves
the clock-syntax regression and preserves datetime/date corroboration; it
does not establish a successful live Lincolnshire capture or explain the
Northumberland zero-output capture.

## Northumberland date-only template

`wildlife-nwt-date-clock.html` preserves the exact Event root attributes and
the reduced date/time DOM observed by the parent agent in the official
Northumberland event page on 23 November 2026:

https://www.nwt.org.uk/events/2026-11-25-wansbeck-natural-history-group-update-on-beavers-and-other-animals-wallington

The publisher's startDate is exactly `2026-11-25`. Its separate native
`field--name-field-event-time` field reads `19:00 - 20:15`; it does not use
BCN's `field--name-field-event-time-value` field. The date is not a midnight
or noon event time. The parser combines only this strict calendar date with
its independently published explicit clock in Europe/London.

The publisher Place metadata was observed as Middleton Village Hall,
Middleton, Morpeth, NE61 4RA, with point 55.160758, -1.908005. The fixture's
location wrapper is reduced to the existing verified field shape using those
values. Its title, summary and two About paragraphs are explicitly synthetic
controls, not a copy of the publisher narrative. The exact date/time snippets
and root attributes are unchanged.

Regression cases retain aware-datetime corroboration, reject conflicting
duplicate clock fields, incomplete clocks, RSS/date conflicts, date spans,
invalid points and ambiguous/nonexistent London wall times. They also verify
that complete native prose, evidence identity and coordinates survive.
