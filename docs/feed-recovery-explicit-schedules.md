# Explicit publisher schedules for existing registrations

Evidence checked November 22, 2026. This change prepares normal automatic
registration and collection; it does not submit Admin rechecks, approve sources,
write public events, or claim completed recovery.

| Original receipt | Submitted URL | Reviewed HTML collection | Current extraction |
| --- | --- | --- | --- |
| 213 | https://www.forestfarmersmarket.com/ | Same homepage | Two upcoming markets: December 12 and January 9, 9 a.m.–noon Eastern |
| 440 | https://www.algonquinarts.org/ | https://www.algonquinarts.org/calendar.php | 17 performances in the normal 60-day window, using six detail pages |
| 209 | https://www.gravegarden.org/occevents/ | Same calendar page | 29 nightly Grand Illumination occurrences, December 4–January 1, 5–7 p.m. Eastern, plus December 19 noon Wreaths Across America ceremony |

## Evidence and bounds

Forest's Wix page publishes two responsive copies of explicit year/date/time
schedules. They must agree. Generic Saturday wording never creates dates. The
publisher address is `15583 Forest Road, Forest, VA 24551`.

Algonquin's homepage actually links `/calendar.php`; navigation remains exact to
the reviewed original URL and requires that link. The listing's explicit years
skip distant productions before fetching. Missing years are resolved from detail
headers. Individual performance rows supply dates and times, including matinee and
evening shows on one day; a date range never generates daily performances.
Published listing/detail years, weekday labels, titles and address must agree.
At most 12 unique details are allowed; a larger in-window set is held rather than
silently truncated. The normal deadline, robots policy and same-host transport
apply to every request. No ticketing/account/cart URL is fetched.

Old City Cemetery's previously observed robots 403 is historical. The current
robots response and public calendar both return 200, with the exact calendar path
permitted. Normal rechecks still enforce current restrictions. The adapter requires
the explicit month/year heading, bounded dates, `nightly` and complete 5–7 p.m.
hours. The December heading's January 1 finish survives a January 1 refresh. The
separate chapel ceremony has an explicit noon start and no invented end time.
The publisher address is `401 Taylor Street, Lynchburg, VA 24501`.

All three leave coordinates to normal geocoding. Algonquin retains
`60 Abe Voorhees Drive, Manasquan, NJ 08736`. Registration/source identities,
approval, rights, publication and audit safeguards stay in the existing workflow.
The collection refresh schedule and cron settings are unchanged.

## Integration requirement

The main-repository `reviewed_listing_url` helper must admit the three exact
collection URLs, and existing receipt recheck eligibility must recognize the
Algonquin root-to-calendar navigation. Deploy the paired database and collector
changes before providing an actionable original-URL Admin CSV. Ben submits that
CSV; subsequent receipt, approval, staging, publication and Events/Map acceptance
remain to be verified after submission.

## Validation evidence

The focused tests exercise captured publisher DOM, normal registration routing,
source identity, year/time/address conflicts, date horizons, duplicate responsive
content, request bounds, deadlines, robots denial, HTTP 403 and rate limiting.
`tests/fixtures/registered_schedules/capture_manifest.json` records source URLs,
HTTP dates, original body hashes and fixture hashes. Fixtures retain selected
public DOM subtrees; no cookies or credentials are included.

The execution environment's direct DNS lookup cannot resolve these publisher
hosts. Raw bodies were captured through its existing HTTPS proxy with the normal
publisher user agent, after reading and evaluating robots rules with the actual
collector product name. Production DNS/SSRF guards were not bypassed or changed;
live publisher transport acceptance remains part of Ben's existing-receipt recheck.
