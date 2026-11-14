# Atlantic City description preservation and final venue corrections

## Production baseline

The initial and remaining source batches are deployed. Database run [43637780151](https://github.com/roomquestgame/RoomQuestGame/actions/runs/43637780151) applied migration `20261114201707` and verified all 476 repository migration versions. At the first completed remaining-batch readback, 18 sources had complete production snapshots and 625 active public events. All 625 public descriptions exactly matched staging, all had full New Jersey postal streets, and the defect query returned zero rows. Twenty-one published narratives exceeded 2,000 characters; the longest retained 5,677 characters.

The seven remaining calendars supplied all 43 expected staged occurrences, with exact publisher-baseline description hashes and streets. Forty were public immediately after collection. Ducktown Tree Lighting is already public through Noyes (`27952327-f835-45d2-a7ab-793f758d3752`), with the same title, December 5 start/end and full street; the normal cross-source identity check correctly suppressed a duplicate. Carnegie Center and Pop Lloyd Stadium need the two verified destination points included in this correction batch. Visit Atlantic City remains a separate production HTTP 403 hold.

## Description corrections

The current publisher captures show no lost prose. Review nevertheless reproduced two future-input failure cases and corrected them across the affected newly added feeds:

- County iCalendar descriptions were checked after HTML normalization but handed to the shared parser in raw form. A raw description longer than 12,000 characters because of layout markup could therefore lose a valid final paragraph before normalization. Each component now normalizes once before the shared limit, including recurrence overrides. Malformed-component and recurrence rejection remain intact.
- Re-parsing already-normalized text as HTML could delete publisher text represented by escaped literal angle brackets. City Library, Stockton PAC, Somers Point Brewing, Seaside Wellness, Smithville and Caroline's now preserve normalized prose through explicit plain-text validation. Anchor retains its required single raw-HTML normalization. Stockton compares normalized text using whitespace only and preserves the established newline join.

Blank and over-12,000-character normalized descriptions still fail explicitly. The correction does not generate summaries, pad short publisher descriptions, or truncate accepted text. Focused regressions cover long final suffixes, master/override recurrence text, escaped literal conditions, blank/oversized rejection and actual worker staging.

The final combined run passed **81 focused tests** across the community, venue, Stockton, Great Day and real category-worker suites. Captured replays found zero description changes for the current County/City Library, Stockton PAC and five venue feeds. Great Day's 13 accepted objects also retain exactly the same narratives, schedules, titles and streets. The changed library recurrence path and all affected modules are included in the consolidated focused test run; unchanged unrelated regional collectors are outside this patch.

## Reviewed venue corrections

The exact Carnegie Center name and full street receive the NJDEP building point, with the historic Illinois Avenue name reconciled against the city's street-renaming record. The exact Pop Lloyd Stadium name and full street receive the official tourism venue's structured point. Both source chains are recorded in [venue evidence](atlantic-city-greatday-final-venues-20261114.json). A different venue or street receives no coordinate from these mappings.

The known street `201 N Pennsylvania Avenue` now maps to the district-confirmed Pennsylvania Avenue School. The publisher's contradictory November 19 event remains held; the fix prevents that incorrect school label from leaking into a future correctly addressed event.

## Publication boundaries

Full normalized descriptions are retained in staged and production event records. Anonymous discovery and SEO pages continue to apply EventQuest's existing publication-rights rules; they can withhold text or show a permitted excerpt. No rights approval or terms review is invented by this rollout.

Oceanside I and II re-download the current publisher-linked English PDFs and extract their full native narratives each time. The reviewed grid dates and clocks are bound to the exact November editions. A changed PDF edition fails explicitly until its date mapping is reviewed; November schedules are not projected into later months.

This multi-source correction is deployed once as a collector release. Final public counts and description/street readbacks are recorded in the application repository's Atlantic City production evidence after recollecting the corrected Great Day source.
