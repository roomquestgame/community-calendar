# Raleigh follow-up: ComedyWorx and Chapel of Bones

Verified November 15, 2026, using ordinary anonymous requests in the research
workspace. This evidence establishes research access; production transport must
still be observed after enrollment. Existing disabled sources were not retried.
No login, challenge solver, proxy, user-agent change, or robots exception was used.

## Exact source profiles

| Source key | Registered HTML URL | Request hosts | Timezone |
| --- | --- | --- | --- |
| `comedyworx_raleigh_nc` | <https://www.comedyworx.com/upcoming-shows> | `www.comedyworx.com` | `America/New_York` |
| `chapel_of_bones_raleigh_nc` | <https://chapelofbones.com/events/> | `chapelofbones.com`, `www.tickpick.com` | `America/New_York` |

Both profiles use kind `html` and platform adapter `html`. Public descriptions
and media are captured as publisher evidence; access does not assert publisher
consent or a reuse license.

## Discovery and complete calendar proof

### ComedyWorx

The official upcoming-shows page publishes a `wix-warmup-data` JSON model for Wix
Events app `140603ad-af8d-84a5-2c80-a0f60cb47351`, component `comp-l37lv4zi`.
The model contains 18 explicit upcoming event IDs, slugs, schedules and native
locations, with `hasMore=true`.

The same page's native application configuration identifies the public script:

<https://static.parastorage.com/services/events-viewer/1.4404.0/widgetController.bundle.min.js>

That script's `loadEvents` call defines the anonymous GET route:

`https://www.comedyworx.com/_api/wix-one-events-server/web/paginated-events/viewer`

Its exact query is built by `comedyworx_calendar_url(offset)`:

`offset=N&filter=1&byEventId=false&members=false&paidPlans=false&locale=en-US&recurringFilter=2&filterType=2&sortOrder=0&limit=18&fetchBadges=true&draft=false&compId=comp-l37lv4zi`

The request uses the public anonymous instance token embedded in that official
page as its `Authorization` header. It is scoped to the exact published app,
instance and site, with no member identity or permissions. The token is ephemeral:
it is not in checkpoints, committed fixtures, logs or this evidence. A resumed
listing chunk reads it afresh from the official page. The module exposes
`valid_comedyworx_calendar_request(url, public_instance)` for the exact guarded
transport; no other host, query, component or authenticated scope is accepted.

The observed next page at offset 18 returned 13 rows, `total=31`, and
`hasMore=false`. The two pages contain 31 unique event IDs and their order is
chronological. All 31 dates fall within the reviewed 60-day window. The latest
currently published date is December 21; no dates are fabricated after that.
The old month calendar and historical sitemap were not treated as complete.

All 31 official `/event-details/<native-slug>` pages returned HTTP 200. The
rendered About section contains more content than the list teaser and the legacy
`about` field in the Wix model. The collector preserves the full native
`[data-hook="about-section"] [data-id="content-viewer"]` content, and validates
the native event ID, canonical URL, title, scheduled status and showtime.

Wix occasionally retains fractional seconds in native end timestamps while its
public schema and visible hours use whole seconds. The comparison ignores only
fractional-second precision; a different whole second, minute, hour or date is
held. The public schema determines the emitted time. Doors text never creates an
additional occurrence.

Each record retains its own published location and paired matching coordinates.
The native formatted address sometimes places `USA Ste. 123` after the ZIP. The
collector moves the supplied suite into the street, removes the country display
token and uses the same event's published postal code. No suite or ZIP is guessed.

| Normalized native address | Records |
| --- | ---: |
| 3801 Hillsborough St Ste. 123, Raleigh, NC 27607 | 2 |
| 3801 Hillsborough St Ste. 123, Raleigh, NC 27607-0168 | 28 |
| 3801 Hillsborough St Suite 121, Raleigh, NC 27607-5206 | 1 |

All 31 coordinate pairs match the event's own `location.coordinates` and
`fullAddress.geocode` fields and lie in North Carolina. The provenance marker is
`publisher_event_geo` and the evidence URL is the exact event detail.

### Chapel of Bones

The official calendar embeds company ID `chapel-of-bones` and this public script:

<https://www.tickpick.com/organizer/api/widgets/tickpick-events-widget.js>

The script explicitly defines read-only JSON POST requests to:

- `https://www.tickpick.com/organizer/api/get_organizer_page_bootstrap`
- `https://www.tickpick.com/organizer/api/get_organizer_events`

`chapel_calendar_request(page=N, bootstrap=bool)` builds the exact URL and JSON
bytes. The body contains only the native organizer `param`, page number, empty
public filters, `All locations`, null name filter, `All Types`, empty selected
performer, and bootstrap-only `include_prices=true`. The ordinary publisher UA,
`Accept: application/json` and `Content-Type: application/json` are sufficient.
No token, cookie or user identity is needed. The validator accepts only those
two calendar paths and the exact company and payload shape.

The observed bootstrap returned all 24 upcoming native events and
`total_events=24`. Twenty-one are in the 60-day window; the three outside it are
on January 28, February 16 and March 24. There are no duplicate event identifiers.
The declared total governs pagination; detail staging cannot begin before that
total is fully captured.

All 21 native `/organizer/event/<identifier>` detail URLs returned HTTP 200 and
contain event-specific JSON-LD descriptions, explicit local UTC offsets and
PostalAddress objects. They identify the same Chapel of Bones organizer. The
published street is 658 Maywood Ave/Avenue, Raleigh, NC 27603. Coordinates are
absent, so they remain null for the existing geocoder; provenance is
`publisher_event_address_pending_geocode` with the exact event detail URL.

The listing serializes local wall clocks with a literal `Z`; treating that as
UTC would shift every event by five hours. Only the detail's explicit offset
determines time. The list and detail must agree in local wall-clock space.
Seven details explicitly label the schema clock as Doors and provide a later
Show, Showtime, Music or Event clock. The collector uses that explicit show
clock only when there is one matching doors clock and one unambiguous later
same-day show clock. Otherwise conflicting times are held.

| Native event ID | Date | Doors | Published show start |
| --- | --- | --- | --- |
| 18935 | November 15 | 6:00 PM | 7:00 PM |
| 19254 | November 21 | 9:00 PM | 10:00 PM |
| 18471 | November 27 | 8:00 PM | 8:30 PM |
| 19122 | December 4 | 8:00 PM | 8:30 PM |
| 18934 | December 11 | 8:00 PM | 9:00 PM |
| 19074 | December 12 | 7:00 PM | 8:00 PM |
| 18291 | December 18 | 6:00 PM | 7:00 PM |

Unknown end times remain null. Weekly/monthly titles and the market's festival
flag do not expand into additional dates.

## Checkpoint and transport contract

The shared worker supplies ordinary guarded GET plus the exact
`read_public_events` callback. Requests are identified by
`chapel_bootstrap`, `chapel_page`, or `comedyworx_page`. The callback applies the
same robots, host, DNS, pacing, redirect, timeout and body-size protections as
other publishers. A publisher 403 or robots failure remains a stop condition.

Each source has a 200-record/200-manifest limit, a 20-page limit and an 850,000-byte
checkpoint limit. Overflow is visible and does not produce a truncated success.
Checkpoints keep the original 60-day window and expire after four hours.

`checkpoint_complete(state)` requires all of:

- `phase == "details"` and `listing_complete is True`;
- `listing_pages >= 1`;
- `listing_raw_count == listing_total == manifest_count + outside_window_count + nonpublic_count`;
- `cursor == manifest_count == len(queue)`;
- accepted event count plus held diagnostic count equals `cursor`.

Partial chunks return `events=[]`. Every native occurrence is processed once in
the durable queue, and accepted rows have stable source/URL/showtime identities.
Descriptions are retained through 12,000 characters; larger descriptions are
held rather than truncated. Missing prose is explicitly diagnosed.

## Validation result

The frozen full replays used November 15, 2026, 13:00 UTC as the window anchor.
All accepted rows passed the shared `validate_records`, `validate_checkpoint`
and `checkpoint_complete` gates, as well as the module's checkpoint validator.

| Source | Raw manifest | Accepted | Held | Outside window | Checkpoint bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| ComedyWorx | 31 | 31 | 0 | 0 | 54,222 |
| Chapel of Bones | 24 | 21 | 0 | 3 | 35,011 |

There are zero blank-description exclusions in this capture. Accepted
ComedyWorx descriptions contain 305–904 characters; Chapel descriptions contain
67–969 characters. The shortest Chapel entry still has its entire published
event-specific admission/earplug/doors/music text, rather than a missing-body
substitute. No full captured publisher prose or public instance token is
committed in fixtures.

Twenty-five focused local tests cover exact transports, anonymous scope,
pagination and complete-only staging, native identity, full body retention,
paired coordinates, public address normalization, literal-Z time handling,
doors/show distinction, missing/oversized prose, recurrence non-expansion,
checkpoint tampering and overflow. Cross-provider overlap is a separate audit;
52 accepted source rows are not asserted to be 52 net-new public events.
