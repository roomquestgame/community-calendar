# Civic and public-service collectors

Prepared November 10, 2026. This cohort extends the existing collector; it does
not establish deployment, successful live collection, source activation or
publication. The companion backend starts six new registrations pending, with
unchecked health, unreviewed rights and disabled coverage. The existing South
Hill town calendar is reused, including its existing source identity.

## Reviewed sources and coverage

All seven sources use `America/New_York`. Registration, collection and public
visibility are separate states. Fixture counts below describe a fixed replay.

| Source key | Official source | Supported scope and material holds |
| --- | --- | --- |
| `richmond_va_legistar` | [Richmond meetings](https://richmondva.legistar.com/Calendar.aspx), [event API](https://webapi.legistar.com/v1/richmondva/events) | Reviewed `json/legistar` tuple; up to five 100-row pages, bounded previous-seven-day/next-60-day query. Missing or ambiguous meeting times are held. Fixture: 13 meetings. |
| `alexandria_va_legistar` | [Alexandria meetings](https://alexandria.legistar.com/Calendar.aspx), [event API](https://webapi.legistar.com/v1/alexandria/events) | Same bounded adapter with its own client and stable jurisdiction identity. Fixture: five meetings. Neither API is a nationwide unified calendar. |
| `virginia_commonwealth_calendar` | [Commonwealth Calendar](https://commonwealthcalendar.virginia.gov/) | Only the publisher's current seven-day window. Embedded calendar-template facts are parsed locally; Google is not fetched. Of 72 captured rows, 69 are eligible and three All Day board/committee meetings are held for unresolved times. |
| `virginia_dmv_connect` | [DMV Connect locations](https://www.dmv.virginia.gov/locations/dmv-connects) | Permitted first page only: ten of 15 visits in the fixture. Robots-excluded query/pagination paths are not requested. Published hours, lunch closures and appointment conditions remain attached. |
| `clarksville_municipal_notices_va` | [Town news](https://clarksvilleva.org/news/), [reviewed Veterans Day closure](https://clarksvilleva.org/7444-2/) | First news page, at most six required article details. Only explicit dated office closures and explicitly timed council meetings qualify. Publication dates and unbounded leaf-collection announcements do not become occurrences. |
| `south_hill_public_works_va` | [Municipal services](https://www.southhillva.gov/municipal_services/index.php), [publisher-linked household guidance](https://www.meridianwaste.com/guidelines/meridian-waste-lunenburg-hauling/town-of-south-hill/) | Published third-Wednesday bulky-item collection, by request. Eight-week expansion; contact/booking requirement retained. No household trash route or arrival time is inferred. |
| `south_hill_town_va` | [Town calendar](https://www.southhillva.gov/calendar.php), [registered Revize feed](https://www.southhillva.gov/_assets_/plugins/revizeCalendar/calendar_data_handler.php?webspace=southhillva&relative_revize_url=%2F%2Fcms2.revize.com&protocol=https%3A) | Existing mixed calendar, with opt-in administrative notices. Unknown all-day activity times and the captured Thanksgiving noon/12:30 conflict remain held. Ordinary timed events retain their prior identities and media behavior. |

See [fixture provenance and factual boundaries](../tests/fixtures/civic/README.md).
The reusable [Legistar field/API documentation](https://webapi.legistar.com/Help/Api/GET-v1-Client-Events)
does not authorize adding unreviewed clients or using token-restricted feeds.

## Dates, applicability and retention

The nested `civic` v1 object carries kind, topic, stable jurisdiction ID,
applicability, source URL, verification time, visibility expiry, source timezone
and explicit time precision. Service-area identity and household lookup URLs
are included only when supported by publisher evidence.

Date notices carry `starts_on` and exclusive `ends_on`. Their UTC timestamps
are transport/query bounds, not midnight appointment times. They have no
invented venue or map pin. Timed meetings and DMV visits retain their actual
published event facts and the existing venue-resolution requirements.

The **24-hour refresh target is separate from visibility**. A failed refresh
does not shorten an otherwise valid service date to 24 hours. `valid_until`
uses the published end/deadline or exclusive local-date end. When a timed
meeting has no published end, `ends_at` remains null; only the existing internal
visibility fallback uses start plus three hours.

## Verified recurring service rules and exceptions

`civic_schedule.py` expands a reviewed rule through a rolling 56-day window.
Weekly rules require a published weekday; alternate-week rules also require a
verified anchor. Monthly rules specify the ordinal weekday. Effective dates,
service-area details and booking requirements come from the publisher. A town
name or a nearby address does not identify a household's collection schedule.

Occurrences use `civic-schedule:<schedule_id>__<original-date>` identities.
Explicit, sourced holiday exceptions can move or cancel that occurrence;
absence from a page never establishes cancellation. A move preserves the ID
and `original_date`, changes the actual date and expiry, and retains exception
evidence. A later cancellation of a moved pickup retires that same ID.
Exceptions are bounded to 31-day displacements, at most 100 exceptions and
100 output occurrences.

Explicit revisions are emitted even when their replacement falls outside the
ordinary display window or has recently ended. The companion backend matches
expired revisions to existing identities and schedule evidence, then removes
them from public visibility. An absent negative revision does not create a
public notice. Finite Revize administrative notices similarly use stable
`revize:notice:<vendor-id>` identities. Ordinary Revize event IDs are unchanged.

## Finite ICS notices are opt-in

The shared ICS parser supports explicit, finite RFC `DATE` service notices only
when the server supplies the civic contract, jurisdiction and timezone. It
preserves exclusive ends and whole-day durations. Date recurrence rules and
exceptions remain held pending publisher-specific identity review. Meetings
without advertised times and ordinary activities are not reclassified as
service notices. **No new municipal ICS endpoint is enrolled in this cohort.**
Calendars without the opt-in retain their existing behavior.

## Claim and publication contract

New civic adapters require the exact registered source tuple, integer
`civic_contract_version=1` and expected stable `civic_jurisdiction_id` before
network access. A jurisdiction's display name is not source identity. Existing
South Hill civic additions and finite ICS notices also require explicit opt-in.
The read-only audit constructs reviewed payloads with those same fields.

The normal backend category claim supplies the capability and opens the
collection run. The worker uses the shared robots, DNS, redirect, host, body-size,
deadline and pacing guards, then the existing token-scoped staging callback.
Timed events continue through canonical event publication; dated or explicitly
marked no-pin administrative notices enter the companion notice handling.
Preview v2 handles the new sources, including Legistar in the existing HTML
category lane. The existing South Hill Revize path retains preview v3 because
its ordinary events already use that capability. The new adapters claim no
photo capability. No timer or separate publication route is introduced.

## Read-only audit and verification evidence

Run locally from the repository root:

```bash
python scripts/capture_civic_sources.py \
  --overall-seconds 480 --output /tmp/civic-sources-audit.json
```

The inventory is fixed at the seven reviewed sources. The audit uses
`preview_source`, never claims work, creates demand, calls database RPCs,
stages or publishes. Each source receives a bounded deadline; the overall
deadline cannot exceed 600 seconds. Failed sources still receive safe receipts
and make the command exit nonzero. Counts are candidates within the declared
source scope, not published-event counts.

For final-head network evidence, manually run **RoomQuest Provider Tests** with
`civic_live=true`. The existing workflow runs focused civic tests, prints safe
receipt counts and limits, and preserves `civic-sources-audit-<commit-sha>` for
14 days, including on audit failure. Receipts include the commit SHA and
collector file fingerprints. No push trigger or schedule was added.

The reviewed combined baseline passed **473 tests and 30 subtests** on November
10. After the move-to-cancellation and capability-gating additions, the combined
local run passed **507 tests and 30 subtests**. Record final-head CI separately
in the release receipt. The workspace
guarded audit at `2026-11-10T01:34:51Z` attempted all seven sources and returned
`dns_unavailable` for all seven, with `complete=false`. Those are environment
resolution failures, not publisher denials or verified network/publication
success. Keep new registrations pending until the guarded final-head evidence
and the normal backend approval/activation gates are satisfied.
