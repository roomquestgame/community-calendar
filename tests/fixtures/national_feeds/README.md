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
