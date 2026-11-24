# EVE-159 — Publisher-linked legacy WordPress subscription discovery

WordPress historic calendar plugins sometimes publish an ICS subscription
under a route that does **not** end in `.ics`.

The shared registration/venue discovery now recognizes *actually linked*
calendar-wide `/events/ical-feed` (or a small set of known calendar base
segments), and the historical All-in-One Event Calendar Timely exporter
`?plugin=all-in-one-event-calendar&controller=ai1ec_exporter_controller&action=export_events&no_html=true`.
The exporter route is accepted only with the exact required query contract
and optional `no_html`; category/tag/individual-event filters are refused
rather than silently dropping other events.

The code does **not** propose or guess these paths on a page where they are
not linked. It does **not** fetch a new URL directly or register a source.
The original first-party same-host, scoped-endpoint, robots/pacing, ICS
VCALENDAR structure, first-event parse and publisher access checks all remain
in force. Single-event download links are not subscriptions.

This is a small compatibility extension to the existing ICS collector, not a
new WordPress parser, endpoint, database migration or scheduler. It is
particularly useful for legacy Event Manager/Timely and some TEC
subscription add-ons; do not assume any of the ten London pages actually
expose these subscriptions without first-party evidence.

Publisher documentation:
- https://wp-events-plugin.com/documentation/event-ical-feeds/
- https://wordpress.org/plugins/event-organiser/
- https://github.com/bernskiold/events-calendar-ical-feeds
