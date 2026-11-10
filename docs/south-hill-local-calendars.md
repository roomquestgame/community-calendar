# South Hill local calendar expansion

Ben approved this batch on November 10, 2026. It adds three reviewed direct
calendar adapters and supplements the existing Town of South Hill source with
its current holiday-market documents. Source enrollment and approval live in
the paired `roomquestgame/RoomQuestGame` migrations. This repository does not
create demand or approve sources.

| Source key | Exact feed | Scope |
| --- | --- | --- |
| `mcgregor_hall_henderson_nc` | `https://www.mcgregorhall.org/shows-events` | Explicit dated show-card performances at the verified McGregor Hall venue. |
| `victoria_town_calendar_va` | `https://victoriava.net/calendar-of-events` | Explicit dated municipal calendar cards; missing event venues remain held. |
| `vance_county_arts_council_nc` | `https://vanceartscouncil.com/events/` | Bounded official listing/detail pages with matching event identity, schedule, and venue evidence. |
| `south_hill_town_va` | Existing Revize JSON feed | Preserve existing records and add dated facts from the PDFs linked at `https://www.southhillva.gov/farmers_market.php`. |

All use `America/New_York` and the existing shared 60-day event window.
Source selection coordinates never become event venue coordinates. The backend
retains the existing 96-hour successful-refresh policy and genuine-demand path.
Ordinary publisher transport, robots policy, host/redirect guards, pacing,
document limits, and deadlines remain mandatory.

## Facts and holds

McGregor uses printed dates and clocks rather than a show-card performance-count
heading. Unrecognized schedule lines cannot silently disappear from a successful
snapshot. No end time is invented. Images come from the actual show card, with
the calendar listing retained as their evidence.

Vance's current concert has a full McGregor Hall address. Its misconfigured
structured UTC clock is reconciled only when the visible local schedule,
listing/detail date and wall-clock components, and complete North Carolina
venue agree. The discrepancy remains in diagnostics. Event-specific image
metadata is not re-dated from an old filename. The parade's organizer mailing
address does not become a parade venue.

Victoria's current four cards have dates but lack occurrence-specific venues.
They remain explicit holds. Town Office footer text, an earlier meeting notice,
and a different month's skating announcement do not supply those missing facts.

Town market links and explicit years, dates, clocks, and streets are discovered
from the current publisher documents. The $25 amount on the forms is a vendor
fee; attendee admission remains unknown. The seasonal May–October farmers
market does not imply a November weekly recurrence. Failed or conflicting
supplemental documents cannot certify a partial combined Town snapshot.

## Safe release order

The Town PDF supplement runs only when the claim contains the exact integer
`south_hill_market_contract_version: 1`. Missing, boolean, string, or unknown
versions retain the existing Revize-only behavior. Existing Civic capability
markers remain intact.

This permits deploying the collector before the paired backend migration.
That migration adds the narrow Town evidence route and advertises the capability.
New direct sources remain pending/disabled until their separate guarded
activation. A source with no valid current candidates is not made publicly
ready solely because its webpage was reachable.

The pinned `pypdf` dependency is included in `pyproject.toml`, which Vercel uses
for runtime dependencies, as well as the existing requirements file.

## Validation

The fixture manifest records raw browser DOM hashes and the derived parser
sections. The Town fixtures include the original publisher PDFs and their
hashes. Browser access is structural test evidence, not successful ordinary
collector access or approval to bypass a hold.

Local validation before the initial branch commit:

- 155 focused expansion and Town tests passed.
- 576 shared worker, evidence, media, Revize/Civic, transport, and Halifax
  recovery tests passed, with 38 subtests.
- All five Vercel build-selection tests passed; diff whitespace, TOML, and
  workflow YAML checks passed.
- Independent review covered source identity/accounting, venue holds,
  local-time reconciliation, and the combined Town route.

Run the reviewed branch's `RoomQuest Provider Tests` workflow with
`south_hill_expansion_live=true` for the read-only ordinary-transport audit.
Optionally also select `south_hill_recovery_live=true` to recheck Halifax and
the previously held local publishers. The recovery audit still runs if the
expansion finds a blocker; a failed audit remains visibly failed.

The expansion audit is limited to the four exact registered profiles, 40 seconds
per source and 180 seconds overall. It verifies source/count/unique-ID binding,
keeps bounded diagnostics, and saves hashes plus optional copies of the actual
public responses used by the parser. Database RPC use is forbidden. Complete
candidate extraction is separate from source activation, geocoding, publication,
and installed-device acceptance.
