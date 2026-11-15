# Boston nightlife production completion — November 15, 2026 UTC

## Scope

This completion fixes the two concrete Burren parsing gaps found during production enrollment and resolves the exact Long Live Roxbury street point. The original release captures and combined 774-row baseline remain unchanged.

## Burren native schedule and descriptions

Production run 6822 failed before staging at 01:21:29 UTC with `boston_nightlife_schedule_changed`. A fresh ordinary publisher capture reproduced the unsupported clock: **10:30am, 12:30pm, 2:30pm, & 4:30pm:** for the December 13 All That Music Academy Winter Showcase. The parser now reads all four explicit shows separately and retains null ends. Unknown clocks still fail validation.

The refreshed calendar also contains a blank teaser for Double Barrell / Mill Street (native ticket event 1930). Its linked detail supplies a full event narrative, which is now hydrated. Blank unlinked descriptions remain held.

The complete refresh contains **123 rows: all 105 original rows are identical, plus 18 native additions, with no changed or removed original IDs and no description holds**. Every row has its full native description and structured street address. The JSON evidence records exact native IDs, emitted IDs, times, URLs and description hashes for every addition.

## Long Live Roxbury location

The publisher’s [Boston page](https://www.longlivebeerworks.com/boston) links its verified [Untappd tap menu](https://untappd.com/v/long-live-roxbury/11948597). That venue identifies 152 Hampden Street, Boston, and its [native hosted-event location](https://untappd.com/v/long-live-roxbury/11948597/event/877264) explicitly binds **42.3278, -71.0748** to that street. The venue map agrees, and the [official contact page](https://www.longlivebeerworks.com/contact) confirms the full 02119 address.

This point applies only to `long_live_roxbury_ma` / `Long Live Roxbury` / `152 Hampden Street, Boston, MA 02119`. The three existing occurrences retain all event details; only coordinates, their provenance/evidence URL and the resolved missing-geometry reason change. Providence organization metadata is not used.

## Verification

- 11 focused Burren / Long Live tests passed, including strict four-clock enumeration, blank teaser hydration and exact source/venue/street point binding.
- The actual category worker, using native captured pages and simulated RPCs, staged exactly 123 Burren rows in four claims and three Long Live rows in one claim.
- Every incomplete claim staged and published nothing. Stage batches contained at most 20 rows, and each completed source made one simulated publication call.
- These receipts verify the worker path locally; they do not claim production publication.
- Complete raw pages and full row exports remain outside the repository. This evidence contains metadata, hashes and exact additions only.

## Lizard Lounge transport observation

Read-only production inspection found three `publisher_http_504` attempts, with the latest at 01:26:39 UTC and ordinary backoff scheduled for 01:30:39 UTC. The source remained approved and queued with zero staged rows. No retry, reset or parser change was made.

[Machine-readable completion evidence](boston-nightlife-completion-20261115.json)
