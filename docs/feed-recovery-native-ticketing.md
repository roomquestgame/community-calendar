# Reviewed native ticketing identities — November 21, 2026

Punch Line registration87/source6123 and Echo Dallas registration338 expose
canonical Ticketmaster event URLs in their official JSON-LD. The same-host native
contract rejected these after ordinary registration, even though the parser
already extracted real records. The ticket URLs remain original publisher facts;
we do not replace them with invented same-host event paths or fetch Ticketmaster.

The exception applies only to these exact JSON-LD calendars, with the existing
native capability and derived source key, and canonical HTTPS Ticketmaster
`/<slug>/event/<16 uppercase hex digits>` URLs without queries or fragments:

- https://www.punchlinecomedyclub.com/
- https://www.theechodallas.com/

Deploy the matching backend contract first: RoomQuestGame PR1625, migration
20261206182500. The unchanged backend source/record validators still require the
completed registration and exact source/feed/event evidence. Source approval,
rights, media candidate handling, publication and96-hour freshness remain intact.

Validation:152 focused collector tests pass, including canonical and near-miss
URLs, capability/adapter gates, original same-host cases and mismatched evidence.
Saved publisher responses replay through the full native adapter to22 Punch Line
and8 Echo Dallas records. The paired captured-helper SQL suite passes36 assertions.
These are local extraction results, not publication claims. Use existing Admin
source6123 resume/review and original receipt338 recheck after both releases;
verify collection, staged/public counts and Events/Map before claiming recovery.
