# NYC remaining arts/public-program sources — second batch

Captured and replayed 2026-11-14. These four profiles contain **66 accepted records**, all with complete nonblank event descriptions and numbered street addresses. They are additions or repairs of sources with zero public events in the baseline. Production deployment is owned by the parent release batch.

| Source | Accepted | Approach |
|---|---:|---|
| Commonpoint public community events (existing 4370) | 10 | Reuse TEC, scoped public Event category instead of thousands of enrolled Class sessions |
| NYU Open to the Public (existing 3550) | 36 | Official LiveWhale JSON with explicitly requested full description, reviewed exact venue and native venue point |
| The Bronx Museum | 3 | Public HTML list + complete native detail narrative/schedule/address |
| Greenlight Bookstore | 17 | Drupal monthly list + complete details, checkpointed three details per chunk |

## Identity and content decisions

Commonpoint retains source key `municipal_mapsee_8ada9fb25b90788ab8a89a73` and URL `https://www.commonpoint.org`; only its profile changes from json/wordpress to html/html. The public Event category (id 4) has eleven records in one page, compared with 1,863 records over 38 pages in the mixed Event/Class calendar. One Hanukkah Festival is held because its machine start says 1am but its prose says 1–3pm.

NYU retains key `municipal_mapsee_59cd82df6a4f146d4b15acec`. Its old ICS contains a valid multibyte em dash split by byte-level ICS folding, which the strict transport cannot decode before parser unfolding. The documented official JSON API returns valid UTF-8 and accepts explicit full-description response fields. The replacement profile is `https://events.nyu.edu/`, html/html. Descriptions absent from the native full-description field remain held; a summary is never promoted into a full body. Explicit online/foreign/internal events, unreviewed venue identities and external destination URLs are excluded. Exact official NYU location IDs and names bind street mappings to the feed's native venue coordinates.

Bronx Museum detail pages provide epoch timestamps, exact `1040 Grand Concourse, Bronx, NY 10456`, and a complete `.show-content` body. Three future programs pass; closure cards and later February programs are out of scope.

Greenlight's JSON-LD concatenates venue names and street values. Structured HTML address components on both list and detail pages resolve the actual venue correctly. This preserves off-site bookseller events at ten different addresses rather than assigning everything to the bookstore. Three monthly pages produce 19 detail entries; 17 pass and two untimed/all-day entries are held. A separate Fantasy Book Group is explicitly “Location TBD” and is held before the manifest. Complete rows are emitted only after the resumable manifest finishes; successful retries reuse the validated complete checkpoint.

## Verification and deployment boundaries

Fourteen targeted tests pass. They cover public category filtering, pagination limits, complete long bodies and missing/oversize holds, the UTF-8 alternative, exact NYU venue/time identity, HTML address handling, checkpoint completion, retry and tamper rejection. The evidence JSON includes every accepted row, full description hash, exact venue street, primary URLs, previous source registration, and long-body verification baselines.

The captures used production User-Agent identities and honored publisher robots rules. Local production DNS validation is unavailable in this execution environment, so direct proxy capture plus parser replay is distinguished from the required production end-to-end run. The production transport guard has not been weakened.

Two unrelated remaining candidates stay held: Queens Museum returns HTTP 202 for robots under the production identity, and New York Transit Museum returns 27 blank-description TEC records requiring detail hydration and meeting-location work. Neither is submitted as incomplete coverage.

The shared address normalizer must accept the genuine New York street names Cooper Square, Washington Square North and Grand Concourse; no fictional Street suffix is added. The release should compare selected long-description hashes after staging/publication and verify all resolved event points. The existing category audit remains unchanged, including its recorded classifier misses.
