# South Hill local calendar expansion

Ben approved this batch on November 10, 2026. It adds three reviewed direct
calendar adapters and supplements the existing Town of South Hill source with
its current holiday-market documents. Source enrollment and approval live in
the paired `roomquestgame/RoomQuestGame` migrations. This repository does not
create demand or approve sources.

| Source key | Exact feed | Scope |
| --- | --- | --- |
| `mcgregor_hall_henderson_nc` | `https://www.mcgregorhall.org/shows-events` | Explicit dated show-card performances at the verified McGregor Hall venue. |
| `victoria_town_calendar_va` | `https://victoriava.net/calendar-of-events` | Explicit dated cards with disclosed, reviewed council/skating venue associations; unresolved parade routes remain held. |
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

Ben subsequently requested street-address lookup and educated venue associations.
Three exact Victoria council/skating occurrences may therefore use the municipal
building at 1809 Main Street and the Community Centre at 1421 6th Street. The
current event dates/clocks still come from the live calendar. Descriptions state
that the venue is inferred, and the retained receipt names the supporting town
agendas, venue directory, or earlier same-activity announcement. Explicit venue
changes win. The Victoria parade remains held with its real route evidence.

The reviewed Henderson parade uses 391 Raleigh Road as an approximate lineup
reference near Burger King, based on the current parade instructions and the
official county tourism directory. Its description preserves that distinction
and the Rose Avenue finish; it does not identify the restaurant as the host.
Spectator admission stays Free while participant entry fees remain separate.

The existing Discover Halifax adapter also receives bounded venue enrichment.
Research supports numbered addresses for 22 prior holds in eight named venue
groups. Complete event addresses take priority, reviewed venue evidence is
retained, and no supplied coordinates bypass normal geocoding. The Holiday
Living Show's two explicit daytime sessions and Lights for Hope's six evening
sessions are reconciled with the actual narrative rather than the conflicting
field values. The South Boston parade remains held for an addressable route
reference. These research counts are not public-event counts.

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

Victoria, Vance and Halifax venue associations additionally require the exact
integer `venue_association_contract_version: 1`. Missing, boolean, string or
unknown versions preserve the previous venue behavior. The backend retains a
validated evidence receipt and requires an explicit public inference disclosure
with no supplied coordinates. A capability change restarts the Halifax manifest
so an older checkpoint cannot lose the new location provenance.

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

Historical local validation before the initial branch commit:

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

## Reviewed address corpus

The November 10 fixture snapshot now contains 13 expansion candidates: six
McGregor performances, three Victoria council/skating occurrences, two Vance
events, and two Town markets. The four added association records preserve the
nine previously accepted records unchanged. Current-head CI and the normal
transport audit remain separate release gates.
