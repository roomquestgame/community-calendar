# New York continuation batch — 2026-11-15 UTC

Seven previously unregistered calendars are ready for one consolidated source-enrollment batch. Local acceptance contains **260 complete upcoming occurrences**. Production publication remains a separate acceptance gate; this document does not claim those captures are already live.

The existing 62 New York profiles are preserved. All seven additions use the existing HTML collector lane, guarded publisher transport, ordinary demand queue, and staged publication path.

| Source | Official calendar | Complete captured occurrences | Description and schedule handling |
| --- | --- | ---: | --- |
| Freddy’s Bar | https://www.freddysbar.com/events | 22 | Complete native Squarespace detail bodies; 51 blank or links-only narratives held. |
| Strong Rope Brewery | https://www.strongropebrewery.com/events-calendar | 6 | Complete detail bodies at the current Red Hook venue; closures/private events excluded. |
| FAD Market | https://fadmarket.co/ | 27 | Two finite, corroborated 2026 holiday schedules; full native narratives. No automatic annual rollover. |
| Other Half Brewing NYC | https://otherhalfbrewing.com/events/ | 1 | Complete Stout Season narrative at Centre Street. Three blank trivia pages held; nationwide/multisite sales excluded. |
| Eataly New York | https://www.eataly.com/c/classes-new-york | 156 | Both NYC classes and events catalogs: 186 parent products across 11 pages. Each native dated occurrence keeps its own full description and instance URL. |
| Astor Center | https://www.astorcenternyc.com/calendar.aspx | 15 | Complete linked catalog includes later months omitted by the calendar. Native dated occurrences and visible full prose agree. |
| Green-Wood | https://www.green-wood.com/calendar/month/ | 33 | Complete permitted monthly HTML and event detail pages; one members-only item excluded. Restricted WordPress API is not used. |

## Descriptions, locations, and completeness

- All 260 normalized records contain a nonblank full description, numbered street address, New York ZIP, and reviewed coordinates. Descriptions over the 12,000-character contract are held rather than silently shortened.
- Durable checkpoints expose no partial results before a complete source snapshot. Manifests, source identity, URLs, occurrence clocks, full row hashes, and source-specific venue tuples are validated on resume.
- Eataly reuses the existing inert native-data decoder. Its series occurrences come directly from publisher fields. Ticket classes deduplicate only if complete event semantics agree. Two reviewed Soho street/point variants normalize to one documented venue point.
- FAD’s 21 Empire Stores dates and six St. Paul weekend dates are bounded to the publisher’s reviewed 2026 season. The official organizer and Dumbo BID corroborate the year.
- Green-Wood retains detailed attendee instructions. Nineteen records explicitly mark meeting-point precision as approximate: Gothic Arch address points, two exact-URL/body-bound After Hours check-in estimates, the Historic Chapel building centroid, and the Modern Chapel near the main entrance. The full postal addresses remain structured.
- Official NYC Planning address points and NYC building/LPC records establish venue coordinates. Source coverage circles are never used as event locations.

## Original unpublished sources

Greenlight Bookstore and Bronx Alehouse retain their existing access holds. Their latest preliminary checks did not establish a working permitted production route.

Transportation Alternatives’ unchanged public Mobilize API now returns a successful response after an ordinary `robots.txt` 404. The paired backend migration may admit one exact reviewed retry. The production worker must independently recheck access and every publication gate.

Fordham exhausted its ordinary retry cycle with `robots_unavailable` at 2026-11-15 01:17:01.181584 UTC. The collector now records a closed network-reason label and allowlisted numeric TLS/DNS/socket codes, without exception messages, URLs, credentials, new retries, or transport changes. The paired backend migration may admit one exact reviewed diagnostic retry only after this collector is confirmed READY in production.

## Verification and rollout

The seven-source captured-response replay passed source, checkpoint, narrative, street, and coordinate checks. **223 focused tests and 44 subtests passed** across the new adapters, shared New York worker integration, category worker, and safe network diagnostics. No routine CI workflow was dispatched.

The local environment cannot perform the production transport’s direct DNS guard; its direct guarded probe returned `dns_unavailable`. Ordinary publisher captures and local parsing are evidence of payload correctness, not proof of production reachability.

Deployment order:

1. Merge this consolidated collector change and confirm its exact production deployment is READY.
2. Merge the paired backend source registration, description/checkpoint bounds, and exact reviewed retry records.
3. Run the normal current-main database deployment once for the batch.
4. Verify actual source completion and staged-to-public description/address equality, then commit the production receipt in the app repository.

Machine evidence: [collector acceptance](../../docs/evidence/new-york-continuation-collector-20261115.json). Full normalized onboarding records, SQL contract checks, source classification measurement, and production receipt belong to the paired `RoomQuestGame` batch.
