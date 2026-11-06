# South Hill publisher fixtures

Captured from public publisher routes on November 6, 2026. Test clocks are fixed
to that date; publisher dates, IDs, addresses and descriptions were not shifted.
Tests that add or alter an event use explicit in-memory synthetic mutations.

## Town calendar

`town_20261106.json` contains all 42 records from the JSON endpoint constructed by
the official [calendar](https://www.southhillva.gov/calendar.php) and its linked
Revize JavaScript:

```
https://www.southhillva.gov/_assets_/plugins/revizeCalendar/calendar_data_handler.php?webspace=southhillva&relative_revize_url=%2F%2Fcms2.revize.com&protocol=https%3A
```

The raw response SHA-256 is
`2087d02fac98b0c8fca3e0c26c0c096655222c7b3e9d29e9cb57f4ae178af942`.
The fixture is pretty-printed JSON. The calendar exports ICS in the browser;
there is no reviewed subscription URL. `/robots.txt` returned HTTP 404.

The [November 9 agenda](https://www.southhillva.gov/261109%20Regular_DRAFT.pdf?t=202611041628380)
explicitly confirms the in-person 7 p.m. meeting at temporary location
111 E. Danville Street, South Hill, VA 23970. The public
[town parks page](https://www.southhillva.gov/parks.php) identifies Centennial Park;
the [official Chamber homepage](https://www.southhillchamber.com/) identifies its
Centennial Park concert venue as 225 E. Danville St, South Hill, VA 23970.
These support exact named-venue mappings, not a default publisher location.
No coordinates are supplied by these fixtures or mappings.

## Chamber calendar and exports

Listing: <https://members.southhillchamber.com/calendar>

Each captured detail uses the same host and `/calendar/Details/` plus its slug:

| Fixture prefix | Publisher slug |
| --- | --- |
| `chamber_customer` | `annual-customer-appreciation-day-1734865` |
| `chamber_prompting` | `ai-for-business-practical-prompting-for-everyday-work-1927017` |
| `chamber_marketing` | `build-a-marketing-plan-you-will-actually-use-1948864` |

The no-query canonical detail routes were separately verified HTTP 200. Linked
downloads are `/calendar/ICal/{same-slug}.ics`; they are one-event exports, not
whole-calendar feeds. The original ICS UIDs are `e.4800.1464252` (customer event)
and `e.4800.1637639` (prompting workshop). The publisher's own ICS links use an
`/events/Details/…?sourceTypeId=Hub` alias; listing links use `sourceTypeId=Website`.

The HTML fixtures retain the observed calendar/event container, linked export
anchor and Event JSON-LD. Global navigation, footer, unrelated JavaScript and
embedded maps are removed. This prevents test fixtures from depending on
publisher chrome or including irrelevant map credentials. The JSON-LD's
date-only end dates are not interpreted as actual attendance times; the dated
listing, visible event schedule and linked ICS must agree.

Robots returned HTTP 200 with an empty `Disallow` plus `Disallow: */TellAFriend`.
Listing/detail/ICS routes are permitted. No registration, email, map-provider,
legacy `/api/events`, or restricted endpoint was requested.

Current expected normalization is three town occurrences and two Chamber
records. The all-day Christmas listing is held; closure records are excluded.
The marketing workshop's explicit two-hour narrative conflicts with its
ninety-minute schedule and is held. The January workshop remains outside the
60-day window. The SOVA workshop's actual South Boston geography is retained.
None of these counts establishes production publication or resolved venue geo.

Both adapters intentionally emit no image candidate. The fixtures retain
publisher image fields where present so tests prove that generic placeholders
do not become photographs. Explicit cancellation fixtures are synthetic
regressions; the captured publisher events do not assert cancellation.
