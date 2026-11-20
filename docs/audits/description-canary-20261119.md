# Ten-feed description canary — November 19, 2026

Executed in isolated staging; no production writes or permissions changes. Actual publisher refresh, then baseline replay of identical responses. All event identities and non-description fields matched.

2,585 events; all have descriptions. Nine longer, zero shorter, 3,654 additional characters; 122 encoding repairs; 23 title-based cancellation/reschedule holds. No invented text.

| Feed | Events | Longer | Encoding repairs | Holds | Max characters |
|---|---:|---:|---:|---:|---:|
| Boise Public Library - Library! at Bown Crossing, Library! at Cole & Ustick (Boise, ID) | 196 | 0 | 0 | 8 | 1897 |
| Fountaindale Public Library (Bolingbrook, IL) | 317 | 0 | 104 | 0 | 200 |
| Montgomery County Public Libraries - Rockville Memorial, Twinbrook, Potomac (Washington) | 249 | 0 | 6 | 0 | 199 |
| Seattle City Calendar | 379 | 7 | 0 | 15 | 2950 |
| St. Mary's County Library (St. Mary's County, MD) | 220 | 0 | 12 | 0 | 200 |
| Main Street Takoma (Takoma Park / Takoma DC) | 182 | 1 | 0 | 0 | 2254 |
| Reston Community Center | 144 | 0 | 0 | 0 | 1523 |
| Omaha Public Library | 221 | 1 | 0 | 0 | 2912 |
| Lincoln City Libraries | 308 | 0 | 0 | 0 | 825 |
| Atlantic County Library System | 369 | 0 | 0 | 0 | 736 |

The upstream Fountaindale, Montgomery and St Mary’s ICS feeds provide descriptions of at most 200/199/200 characters in this sample. Removing our collector limit cannot recover omitted source text. Event detail-page enrichment is a separate next step.

Public web eventHtml has a separate 600-character display cap. The accompanying app patch removes it for text already supplied by the public projection; metadata stays concise and withheld raw descriptions remain withheld. The production RPC cap and permission rules are unchanged. Native EventDetailsAbout already retains its entire supplied string and expands beyond four lines; source audit only, no device run.

Fountaindale production check: source approved/healthy/ready, 418 included staging rows (308 upcoming), zero missing coordinates. One external event exists for its source key; no community_area_sources association. Publication/demand coverage needs follow-up; description permissions alone do not explain the event publication gap.

Validation: 50 collector tests passed locally and in remote sandbox. Five focused web rendering/security tests passed, including a 15,000+ character description. Three unrelated existing web tests fail on the pinned baseline (button text/header assertions); the same three fail after this patch.

Review outcome: collector recovery is demonstrated, but this is not a production rollout. Runtime staging snapshot is temporary; this report preserves aggregate results and response hashes. Private before/after examples are retained separately, not committed to the public collector repo.
