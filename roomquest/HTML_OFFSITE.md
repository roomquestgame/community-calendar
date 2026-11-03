# Virginia HTML offsite venues — November 3, 2026

Ben approved fixing the missing Clarksville meeting from a Boydton-area search. The collector must keep legitimate offsite events with their actual meeting venue, not discard them because the publisher is a park or assign the park entrance pin.

## Behavior

- Extract an explicit Virginia street address directly attached to the event's named Program Location in publisher prose.
- Keep Clarksville Town Hall as the venue and its supplied address as the geocoder input. Do not hardcode a Town Hall point or run an external lookup from this parser.
- Preserve the venue paragraph (including Chamber Room) even when the first paragraph only describes the sponsoring group.
- Unknown coordinates remain null for the existing shared address-cache/geocoder pipeline. In-park activities retain the owner-reviewed park coordinates.
- Conflicting addresses, unrelated travel/shipping addresses, and genuinely unresolved offsite venues are not guessed. No broad parser support is claimed for all prose layouts.
- The HTTP route remains `/api/html-demand`; provider identity remains `html`. No ICS, WordPress, JSON-LD, or other collector paths are changed.

## Evidence and limits

The official DCR meeting listing supplies the Town Hall location and street address in its description. Synthetic parser fixtures cover that layout without representing fabricated events as live captures. Seventeen focused local parser tests passed, with only the upstream record-conversion import stubbed; these are not a deployed end-to-end test. Full native provider CI must pass before merge.

Backend companion: `20261103134500_html_offsite_address_resolution_continuation.sql` extends existing demand-gated waits and publication resumption to supported HTML sources. Its regression tests exercise staging -> pending address -> synthetic geocoder result -> publication, cache reuse, expired demand, and a paused source.

## Release status

Before activation, deploy the reviewed collector main commit and the normal GitHub Database deploy workflow, including the already merged Occoneechee calendar-URL correction. Then verify the source and approve only the reviewed pilot through the established workflow. At the read-only production check on November 3 at 11:49 UTC, Occoneechee was still pending/unreviewed/idle and had zero published events. No production activation, event insertion, or geocoder request occurred during this implementation. Do not call the meeting visible until the live ingestion and search results have been checked.
