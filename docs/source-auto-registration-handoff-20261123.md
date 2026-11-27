## November 26 — EVE-156 release follow-up (initial pilot remains disabled)

Backend #2137 merged b83a386ec6cfa830e64a2290b9250fbd8585fbe7; protected migration 20261207070000 requires live ledger readback. New SQL rollback controls passed for exact pilot scope, durable UTC-day usage even after lookup cleanup, no same-host proposal bypass, and existing lease/geocoder. No production activation or paid inference. Collector research tests 37/37 on exact blobs 874b4f80aca2c2c82baabccee8be5dff1d04ba25 and 86dc434f4a1f19f2b40fdedb8a0c6774fd2c138d. Explicit Vercel OIDC model option; no implicit use of existing crawler search key. Research claim gets 28 seconds only when existing geocoder route has sufficient headroom, preserving its 55-second route budget and ordinary 15-second venue allowance. No new scheduler or worker. Initial NYC-only pilot is exact-key allowlisted, disabled and zero-budget until credentials, usage caps and canaries are verified. Keep EVE-156/EVE-175 open for actual publication and cross-collector US/GB rollout.

## November 26 — EVE-156 shared AI research implementation follow-up (draft; NOT deployed)

Collector PR #594 now contains `roomquest/venue_research.py`, focused tests, and the gated integration in the existing `venue_resolver.run_batch`. Ordinary resolver succeeds first; only a clean NYC miss may request a deferred research lease. The same worker receives the durable permit on a subsequent claim. It searches only explicitly allowed official hosts (Tavily URL leads, never snippets as address proof), fetches via existing DNS/robots/redirect/pacing protections, and sends bounded verbatim page passages to the candidate Anthropic extraction adapter. Exact venue, locality, one numbered street, quote, and optional postal code must agree. The model cannot assign coordinates or publish events. The worker persists the exact accepted proposal before ordinary submit and existing forward geocoding. Configuration is disabled by default; no implicit model or reuse of the crawler's search key.

Companion backend draft: https://github.com/roomquestgame/RoomQuestGame/pull/2137 . SQL is a candidate under scripts/sql, NOT an applied migration. Actual-schema rollback checks passed disabled policy, wrong lease/model, duplicate permit, budget exhaustion, wrong host/borough/quote, exact proposal binding, ACL and existing NYC submit. Post-rollback confirmed no research tables and unchanged gateway. No production mutation, paid request, new queue or schedule.

36 focused offline/mock research tests passed (tested module/test blob hashes 5834cc194567ce4c415e914a028a63510300775a and 318f31ed73929e07c3d54dd15f5c767b071207e7; worker integration diff inspected separately). Input 16 KiB; output 512 tokens; SQL candidate reserves up to 20k input + 512 output tokens per admitted attempt, daily cap defaults zero. Price ceiling/model/credential not selected; verify actual token accounting and timing with canaries before enabling.

Remaining: reconcile #594 with current main (handoff conflict); review and coordinate the forward migration with EVE-170; verify disabled path; explicitly approve search/model provider, model and spend cap and configure credentials server-side; verify NYC canaries using real official evidence, geocoder and normal publication; extend reviewed source/country/locality admission and canonical alias promotion for all applicable US/GB collector families (initial pilot deliberately NYC-only). Do not retry the location backlog wholesale until these acceptance gates pass. Keep EVE-156/EVE-175 open.

## November 26 — Shared venue AI fallback draft (EVE-156 / EVE-175)

Owner approved completing optional AI assistance. This draft adds only a bounded candidate-selection module and ten local tests. It is NOT integrated, deployed or enabled. Existing deterministic resolver, geocoder and queues remain unchanged.

Model may select only from up to three independently verified venue/address/evidence candidates; unknown IDs, extra fields/coordinates, unsupported quotes, locality/country mismatch, invalid JSON and ambiguous responses stay held. One required durable admission callback precedes one model attempt. Caller must still implement trusted candidate discovery, publisher transport validation, durable daily request/token budget and existing lease/provenance handling before integration. No automatic approval or coordinates.

Production collector environment-name inspection found TAVILY_API_KEY but no model API credential. Values were not decrypted or disclosed. Anthropic adapter is an unactivated candidate because anthropic is already an optional dependency; provider, exact model and spending ceiling are NOT selected by this draft. Required next decision: model/provider and approved budget, then server-only credential. Do not run paid inference or claim production acceptance from mocked tests. Tavily search is not an LLM address authority.

NYC's submit contract currently restricts evidence to event host; verified third-party official venue evidence needs a constrained provenance contract, not removal of host validation. Preserve review outcomes and existing worker limits. Complete integration, guarded DB changes if needed, credential configuration, protected deployment, four-venue canaries and normal publication before reporting success. Keep EVE-156/EVE-175 open. No 438-event retry was requested or executed by this draft.

Repository AGENTS references a missing .claude/bram-conventions.md; no substitute guidance was invented. Current owner explicitly approved completing the work after being informed. Available repository cost/deployment/PR and publisher safeguards remain in effect.

## 2026-11-23 — Review-hold batch of 10 and reusable GrowthZone intake detector

Owner approved investigating ten of the existing feed-registration review holds while improving the registration automation, rather than bulk resetting all 73 eligible receipts. Original IDs **77, 79, 91, 129, 226, 328, 331, 441, 561, 878** remain unchanged in production. The linked ten-source audit and **source-status distinction** are in [the batch journal](journal/2026-11-23-held-registration-batch01.md).

The collector change recognizes a native GrowthZone candidate only from a real unfiltered publisher Events Calendar with two distinct same-host detail links, then uses the existing native XML adapter and its configured source-specific timezone to verify complete importability. Missing profile, invalid XML and disallowed publisher requests retain the review hold. It is **not** permission to register generic HTML or guess publisher metadata.

Important dedupe lessons: #561 has a malformed long ICS encoding but the correct Las Vegas Library calendar is **already approved at source #3228**; #878's single article is superseded by an approved collecting official full-content publisher feed **#6212**. Neither should be re-registered or blindly rechecked. The other source-specific holds require complete bounded collection evidence and venue scope validation.

**Prepared only:** a code branch, focused tests and evidence journal. Local tests and browser/collector acceptance have not run, and there is no PR merge, production deployment, Admin recheck, new source approval or newly published event receipt. A signed-in EventQuest Admin browser context is needed to submit future review-approved recheck CSVs. Maintain the owner's no-routine-CI policy.

# Automatic registration repair handoff — 2026-11-23

## UK packed LOCATION address follow-up

The normal PHCL acceptance preview exposed a separate address-contract gap:
47 exact default venue matches had verified points but no separate street
address because the registered-iCal extractor recognized US formats only.
The bounded UK extension preserves native venue names and all existing review
and point gates. It requires an explicit UK country, full postcode, a unique
numbered street and locality; it infers no coordinates or postal town.

The exact 50-event fixture and existing US/equal-end checks pass: 61 tests.
The new output adds 49 native address fields, keeps the 47 exact default bindings,
leaves the film URL untouched, and changes no other emitted fact or occurrence
identity. Seven manual timing Holds remain Admin decisions. The two chess venue
reviews may require a normal re-save after their native address is populated.
See the [address journal](journal/2026-11-23-uk-ical-location-addresses.md).

This branch is reconciled with current main
`e3ad75cfcc32ad416bea2d5047e1d5e0bf359666`, retaining deployed PR #451 merge
`2e8930101da138a44ad5ff6ef8fa840eed3571bf`. Parent-controlled PR/deployment and
ordinary source/public acceptance remain pending for this follow-up. The app's
reviewed-geocode classification fix is already deployed via
[PR #1753](https://github.com/roomquestgame/RoomQuestGame/pull/1753).

## Collector change ready for review

Branch: `fix/uk-venue-auto-registration-20261123`, updated onto main `6f1b4fc`
for PR #451; initial implementation base was `054e161`.
The only production-code change is seven lines in
`roomquest/preview_worker.py::_preview`: an equal aware start/end instant emits
`ends_at = null`. It does not fabricate a finish or make a publication decision.
Native PHCL/RHTS fixtures and 23 focused regression cases accompany the change.

The deployed community publisher already stores missing/non-positive ends as
`ends_at = null`, `end_time_verified = false`; its timed-event expiry fallback
is start plus three hours. This collector adjustment aligns staging and review
with that established contract. It requires no coordinated backend timing
migration. The independent staged-geocoder/base-Hold repair is owned in the
application repository and must be reviewed on its own merits.

Full reasoning, call paths, native URLs and verification are in
[the journal](journal/2026-11-23-zero-duration-calendar-ends.md).

## Existing release integration

Checked-in configuration identifies the Git-connected **Vercel** project
`roomquest-community-collector` in team `room-quest-game`, with production alias
<https://roomquest-community-collector.vercel.app>. There is no Render service
configuration in this checkout. `vercel.json` uses
`node scripts/vercel-ignore.mjs collector`; the runtime change qualifies for a
main-branch build, while previews and documentation/test-only changes are
skipped. The normal release is PR → merge to main → verify a Vercel READY
deployment at the merged SHA. Follow the existing
[build controls](vercel-build-cost-controls.md): no routine CI label or workflow
dispatch. These are repository integration facts, not a fresh live deployment
receipt.

## Review and deployment checks

1. Review the seven-line normalization and native-fixture tests. Positive
   durations, DST folds, all-day records, cancellations, recurrence identity,
   source identity, and publisher access constraints retain existing behavior.
2. Run the documented local focused suite. After the main updates, the current
   result including the three updated adapter suites is 437 passed plus 22
   passing subtests and one unchanged baseline test mismatch: the Tribe
   timezone table has eight reviewed entries, while its test still expects
   seven. All 23 new zero-end cases pass; `git diff --check` is clean.
3. After the parent-controlled release, use normal Admin collection for the
   exact registered PHCL and RHTS feeds. Do not manually update production
   event times through SQL or create a replacement source.
4. Reassess the latest staged occurrence before a venue review or Include.
   End normalization can invalidate a prior venue-review fingerprint because
   that identity includes the end. Manual Holds remain independent decisions.
5. Verify ends are null/unverified for PHCL stages 416610, 416626 and 416644,
   and RHTS stage 416587 (or their current same-occurrence successors). A
   future public event can show its start alone; the expiry window is not a
   displayed finish. Keep RHTS Santa aggregate 416586 held pending its separate
   session contract.

The parent approved creating a normal PR after independent review. No merge,
deployment, production write, source approval, or public acceptance claim is
part of this preparation. The parent owns release and durable regional
reporting. Capability home is EVE-6; Admin findings relate to EVE-10, and local
acceptance to EVE-150/EVE-151.

## November 25 — supported-provider URL routing repair

Owner requested simple URL submission into existing supported collectors.
Tickera/Event Discovery now follow one advertised same-host calendar at common
calendar paths (`events`, `shows`, `whats-on`, etc.), retaining query selectors
and refusing ambiguous or venue-path-widening navigation. Their actual
collector validates the destination before registration. Provider navigation
and native Squarespace collections take priority over page SEO JSON-LD;
verified TEC/GrowthZone native discovery also precedes JSON-LD acceptance.
No new provider types, queue, scheduler, database schema or source resets.

Valid empty Tickera/Event Discovery arrays return empty recurring snapshots;
initial registration still requires extracted events. Malformed Event Discovery
rows with no valid events remain an error. Tickera's documented calendar may
be category-filtered: it represents that configured calendar, not an assumed
publisher-wide archive. Official references:
https://tickera.com/tickera-documentation/event-calendar/
https://info.ticketweb.com/client-website-services/
https://commerce-apis.squarespace.com/view-json-data

Focused URL-to-registration-to-preview and affected provider suites: 120 passed.
Existing outdated TEC reason assertions and GrowthZone registration-probe mock
signature/retry expectations were aligned with already-deployed behavior.
Read-only live state: Motorco #6403 has 11 included staged events; Knitting
Factory #6402 has 15 held for coordinates across four venue-label variants.
Both are approved/healthy/preview-complete and publication-supported. Neither
had a publication request or future public events at this observation.
Local publisher checks could not resolve DNS; this is not publisher rejection.
Required .claude/bram-conventions.md remains unavailable (404). No routine CI.
Release and live acceptance evidence will be recorded in the canonical master.

## November 26 — Event Discovery standard calendar and trustworthy recognition

Continuing broader Feedzilla; Spektrix venue-location holds remain owned by the
separate EVE-174 workstream. Current main at investigation: 67d000ed. Required
`.claude/bram-conventions.md` still returns 404; current AGENTS.md and owner scope
were reviewed. No approved HTML source is an unfinished registration queue.

TicketWeb documents native WordPress Event Discovery with distinct List,
Calendar and Artist views (https://info.ticketweb.com/wordpress-plugin/ and
https://info.ticketweb.com/client-website-services/). Live publisher evidence:
Santos advertises `get_events_for_calendar`, type `calendar`, with exact dialog
fragments bound by event ID to same-response `.tw-name` canonical title links.
The existing collector supported only `get_events_artist_calendar`.

This change admits the evidenced standard action through the existing bounded
form validator and public publisher transport, resolves exact dialog identities,
and preserves canonical URL + original sortkey occurrence IDs. Unknown actions,
mixed action contracts, mismatched dialog titles and incomplete snapshots remain
held. Event Discovery's bundled `eventon_details_shading_bot` CSS no longer
counts as the actual EventON plugin. Real EventON plugin assets/ajde_evcal remain
recognized. No other provider collector, shared worker/claim, queue, schema,
publication or refresh policy changes.

Focused four-suite verification: 70 passed. Replay of the actual Santos public
response: 8 rows, complete, America/Chicago, canonical event links, image URLs,
missing venue evidence retained. Actual Birdland artist response contains 102
cards with additional performance links; accepting only its first URL would
misrepresent completeness. Added a completeness guard; actual replay marks the
snapshot incomplete (47 single-link cards remain but must not stage). Its
calendar also declares America/Denver despite New York venue evidence; do not
invent a replacement timezone or claim publication acceptance.

Original #761 rechecked through signed-in Admin against deployed #564: parent
now links canonical Tockify child #1562, which is disabled/robots_denied. No
source was created and no alternate endpoint is authorized. Original #1298
followed deployed calendar navigation to child #1563/source #6456, collected
148 under the predecessor; new completeness finding requires correction before
acceptance. #1334's deployed navigation recheck retained the stale FullCalendar
hold because the standard action was unsupported. Recheck only after this
release. Live production acceptance and exact deployed SHA remain to be added.

### November 26 — production readback and specific-plugin precedence

#580 deployed READY as `8a66e72fe9201c2468cdcea6dfb460f9bea23891`,
`dpl_4e8S9kf3e6wyPLt5RVSdi7wff576`, canonical production alias present,
no alias error. Original Santos #1334 rechecked only after release; child #1564
registered native Event Discovery source #6458. Actual ordinary preview completed
8 future events; 0 located/public at initial read. Publisher Contact advertises
1135 Decatur St., New Orleans, LA 70122; no guessed coordinates/default applied.
Birdland #6456 paused through supported Admin after its partial artist inventory
and conflicting publisher timezone were verified; original IDs/stages retained,
0 public events. It cannot be counted as accepted native collection.

Motorco #6403 and Knitting Factory #6402 now have 11 and 15 upcoming scheduled,
non-hidden, located attributed public rows respectively. Their old staged venue
hold reasons do not override actual public membership. Both last successful
collections remain November 25; no new 96-hour scheduled refresh is claimed.
Original Tockify #761/child #1562 remains a genuine robots denial.

A final precedence check found Bourbon #1289's installed Event Discovery plugin
was being described only as linked TicketWeb inventory. Actual script/link
plugin assets now precede the ticket URLs they render, without admitting a feed;
serialized asset text does not establish installation. Full native collection
still must succeed. Four-suite verification: 71 passed. No shared schema/worker
or Spektrix changes. The remaining Event Discovery list-view contract and grouped
artist/timezone evidence require reusable implementation, not a publisher HTML
fallback or a forced publication.

### November 26 final acceptance readback

#581 is production READY at `7ed1ba1843c657c1a1247bed3b17c6375c3d0b60`,
`dpl_9sNdoh4TXifDmc9EHJD4okht84VS`; exact canonical alias/no alias error.
Original Bourbon #1289 now returns retry/event_discovery_adapter_needed after
the authenticated post-release recheck, no source; list-view contract remains
unsupported. Santos #6458 is approved/ok/complete with eight staged venue holds.
Birdland's actual new preview returned incomplete_event_discovery_snapshot;
Admin pause confirmed, original 148 stored stage IDs retained, zero public.

Canonical public pages physically verified for the older canaries:
- Motorco Will Backerman: https://eventquest.ai/e/ce99efd7-e34c-41ad-80e0-56bf12b0b25b
- Boise Dark Harvest IV: https://eventquest.ai/e/db9c4956-a8e1-44d4-a2f9-75ec3443735a

The initial public-page diagnostic used external storage UUIDs and returned
404; `rq_seo_private.event_links.id` is the public URL identity. Correct canonical
pages show local times, actual addresses and publisher attribution. This was a
diagnostic error, not a serving bug. No identity changes were made. Database
cohort visibility was checked for all 26; only these two representative pages
were physically inspected, not the whole Events/Map UI. No later 96-hour normal
refresh has yet occurred; do not call ordinary Admin preview a scheduled-refresh
proof. Canonical master and EVE-6/EVE-159/EVE-156 carry remaining work.

## November26 continuation — Event Discovery complete occurrences and event evidence

Candidate collector change expands only explicit artist-card performance links:
card date and primary sortkey must agree; each exact URL has its own published
clock, preserving existing URL:wall-time identities. Ambiguous clocks, foreign
hosts, conflicting identities and >500 expanded occurrences hold the snapshot.
Saved Birdland response expands149 cards to261 distinct performances. Birdland
remains paused until the bad America/Denver widget zone is explicitly reviewed.

Forward backend63500 enables an Event Discovery-only blank-location handoff in
the existing leased venue queue. Each cache key binds source,event key,title,
URL,start and original blank venue facts. The helper fetches only that exact
event page and reads its publisher-authored Google Calendar export link locally
(no Google request). Title, start, zone, physical US street and canonical/og:url
identity must agree; no footer/contact/default venue is inferred. The one-page
lookup uses the existing15s claim allowance and existing transport caps, so a
10s crawl delay fits without extra requests or changing the pipeline deadline.

Backend also exposes an opt-in reviewed source timezone to this adapter only.
In normal Admin review save the IANA field and an evidence line exactly:
`Timezone verified from publisher event calendar export: https://publisher/tm-event/event/`
The source must be registered, approved, accessible, reviewed, and the evidence
must be on its exact publisher host. Ordinary inferred source zones do not
replace widget timezones. Existing venue defaults and other providers are unchanged.

Focused Python selection84 passed plus4 subtests. Isolated PG18 compiled the
exact live guarded predecessors plus63500 and exercised identity invalidation,
actual CHECKs, stale/manual/online/point/classification fences, gateway submit,
idempotence and reviewed-clock admission. Supporting services are stubs in that
model; this is not a full production-schema replay or live publication claim.
Protected backend deployment and normal canary acceptance remain next.
Bourbon has real next-page links; its first20 list cards are not a complete feed.

## November26 — native failure receipts preserve provider identity

Live triage of original524 finds the installed Event Discovery plugin and its
publisher-linked /calendar. Native collection encountered source_network_error;
this is not evidence for a custom HTML collector. The workflow previously lost
its known p_type on the outer transport-error path. The scoped correction keeps
Event Discovery/Tickera type and exact recognized endpoint on retry/disabled/
review receipts without changing status, publisher access, source creation,
approval, request bounds or retry timing. Spektrix paths are unchanged.91 focused
registration/provider/auto-defer tests pass, including eight native network,
HTTP503, robots and403 identity/decision cases.

Additional diagnostic evidence: Dock Street687, License506 and Boggs1347 have
publisher-linked calendar destinations, but their native Squarespace JSON
requests are explicitly robots_denied. No bypass or generic HTML replacement
was attempted. Official Squarespace View JSON Data and Collections docs were
reviewed; an accessible page alone does not establish an accessible native feed.
These are access blockers, not proof that a Squarespace collector is missing.
None has an existing same-host source; VAStage1150 separately has pending5300,
which must not be duplicated. Bourbon1289 needs a complete native paginated list
contract; first20cards contain no full year/JSON-LD and cannot be accepted as a
complete snapshot. Slim's81 and Gaspar's74 link dedicated event pages; WordPress
alone is not a calendar provider.

Backend63500 and63600 are now protected-deployed (runs45838364129 and45840113024).
Birdland6456 normal retry completed261current stages at14:36:13Z with corrected
New York times; Santos6458 completed8 at14:27:43Z. Old Birdland148stages remain
historical, not additional current performances. At14:37:46Z the existing named
venue helper independently resolved Birdland Theater's315West44thSt address via
venue_contact. Normal geocoding/publication and new exact-event Santos lookups
remain pending; do not claim public or96hrefresh acceptance yet.

## November26 — exact calendar-export titles containing a literal hash

Santos's publisher export for NEW ORLEANS PUNK WEEKEND #2 leaves the title hash unescaped, so normal URL parsing hides the dates/address behind a fragment. Recover only a literal hash inside the text query field whose complete decoded value exactly matches the staged event title. Reject every remaining fragment and retain exact canonical/og:url, event title, UTC start, timezone, unique physical US address and ambiguity checks. No Google request, inferred location or broader fragment decoding. 73 focused tests plus4 subtests pass. Seven other Santos exact-event pages already supplied independently matched publisher addresses; this eighth awaits deployed verification. Existing helper FIFO and normal Admin address review remain distinct acceptance paths.

## November26 — separate native discovery and endpoint verification claims

Stampede524 exhausted six attempts as review/publisher_pacing_deferred. A bounded
first-party probe confirms10s crawl delay, installed Event Discovery, advertised
/calendar, standard get_events_for_calendar and America/Denver. The current
root claim fetches homepage+calendar+render before creating a child, then the
child repeats verification. Discovery now records only the uniquely advertised
same-host scoped native endpoint; the existing independent child claim must
verify complete collection before a source can be approved. This matches native
feed discovery, preserves35s/request bounds and publisher pacing, and adds no
worker, queue, cap, guessed path or direct source insertion. Server endpoint_only
plus parent-derived native hint retains identity on a child transport/access
failure; a direct user hint cannot supply detected identity.112 focused tests
pass, including parent-only fetch and independently robots-denied child cases.
Review original524 only after the relevant deployment, then inspect its actual
child result. A pacing label alone is not proof of an external permanent block.

Correct License receipt reference:506, not1506 (unrelated Spektrix receipt,
untouched). Native Squarespace denial evidence concerns687/506/1347.

## November26 — Event Discovery popup typography identity

Stampede child1593 independently reached its native26-card response after588;
one same-ID dialog failed title identity because raw JSON uses spaced hyphens
and WordPress renders en dashes. Official wptexturize documentation explicitly
describes this exact substitution:
https://developer.wordpress.org/reference/functions/wptexturize/
Normalize only this spaced-hyphen transformation on both compared titles. Keep
case, words, event-ID/dialog uniqueness, trusted URL, wall clock, occurrence ID
and raw emitted title unchanged.124 focused tests pass, including different
word/case/event-ID and missing punctuation negatives. One provider card outside
the60-day event horizon is intentionally not emitted by existing record policy.
The remaining25 eligible cards require deployed replay and ordinary Admin child
recheck after a corresponding guarded backend fix; no partial snapshot accepted.

Live acceptance now confirms Birdland6456 all261current and Santos6458 all8
current native IDs/start times/public verified points visible. Santos manual
address provenance is explicit; normal recollection15:27:29 retained all8 stage
IDs/addresses. Canonical public pages were physically checked for both feeds.
Shared capacity temporarily returned busy, then progressed without cap/priority
changes.96h refresh intervals verified; no elapsed scheduled-refresh claim.


## November26 — unsupported native display identity and live acceptance continuation

Installed Event Discovery/Tickera plugin detection now survives the existing monthly retry conversion as its matching native type. Unsupported variants remain retry/adapter_needed, with no verified endpoint, collector profile, source insertion or publication. Weak provider mentions and mismatched type/reason pairs cannot promote identity. Other providers, access holds and working collectors keep their outcomes. Focused verification: 88 Python tests pass, including submitted URL through registration finish payload (both native plugins), negative identity/access and existing native routing/collector tests. Deploy this change before rechecking original Bourbon1289.

Bourbon1289's policy-aware live root has standard installed Event Discovery plugin assets and20 native list cards, with explicit /page/2/ navigation. It has no date metadata/JSON-LD/advertised calendar feed. One exact native event detail exports full date20261127T200000 and venue1415OStreetLincolnNE through a local Google calendar URL, but ctz=CST is ambiguous and not an IANA zone. No Google request was made. Do not infer a full snapshot from page1, guess a clock, switch to generic HTML or invent a public REST route. A complete bounded native pagination/detail checkpoint plus reviewed IANA contract remains implementation work.

Collector589/f873642 is deployed READY as dpl_DY5TWN2DVfL5YJ6jwb46vVck2b6b. Backend64950 (protected run45852129903) let original Stampede524 retain its parent identity and child1593 recheck register native Event Discovery source6474. Collection complete25 at15:49:23UTC. Native ticket test/chart stages618411/618412 carry explicit manual hold notes and remain unpublished. Individual normal Admin reviews resolved13 lookup identities; ten other public candidates plus two held entries remain pending after publisher browser protocol timeouts and an observed502 gateway error (one recovery unsuccessful). Existing normal geocoder resolved2430SouthHavanaStAuroraCO80014, America/Denver; first two events are public via normal publication. Hector canonical page https://eventquest.ai/e/3ad5052e-2f1a-4bc7-bdc0-4907f33a56f4 physically verified9:30PMMST with correct point and original publisher URL. Normal Admin Preview refresh queued, acceptance pending. Do not claim23public.

Backend2105/2106 ->66150 deployed protected run45859036388 success: an exact-event evidence mismatch remains visible for correction, and normal save rejects another event's URL before caching. All three predecessor hashes guarded,14 read-only SQL controls passed. LadiesNight49's accidentally stale evidence URL corrected through normal Admin; readback exactURL, resolvedstatus and stageaddress match. Other providers/Spektrix semantics unchanged.65350 was never applied and was renamed after Gate1 found concurrent NYC66000 live; no history repair.

Birdland6456 current261/261public (148older stage rows retained, not409current); Santos6458 current8/8public, normal refreshed snapshot15:45:29UTC retained aggregate identityhash76d332758066e186d016d19a10efe384 and renewed last_checked. Motorco6403 11/11 and Boise6402 15/15 remain public.96h scheduled cadence unchanged; elapsed96h refresh is not claimed.


## November26 — final provider recognition and published-feed refresh receipts

Collector590/8157933 deployed READY dpl_CFbWCe42wY59b8kU2MvoS3Sny9Js on canonical alias before original Bourbon1289 recheck. Production attempt3 at16:39:12.585348UTC is retry/event_discovery_adapter_needed with **detected_type=event_discovery**, no sourceID, verified endpoint or publication. The native identity retention fix is accepted in the actual registration pipeline; complete bounded native paginated collection/reviewed IANA clock remains engineering work. Official TicketWeb client-website-services and download-plugin docs rechecked; multiple native view modes are documented. Box plugin-PDF link exposes only a JS shell through extraction; no unobserved endpoint contract inferred.

Stampede #6474 post-publication normal Admin refresh completed at **2026-11-26 16:42:45.714304 UTC**. All **13/13 public events** retained identity hash **8619fadc14d2d1bd6333c2eb3c951c27**; all25 stage IDs/provider IDs/hold notes retained hash **fb7635fc563b5dfc410694adad77660d**. Minimum public last_checked advanced16:37:23.352498→16:42:46.071786UTC. All13 have exact native starts, verified points, America/Denver and visible public state; both explicit ticketing holds remain unpublished (held_public=0). This verifies normal collection→stage→publication→refresh with IDs retained;96h scheduled interval unchanged, elapsed96h cycle not claimed. Ten other public-event candidates still await individual verified venue reviews after publisher detail502/browser failures. No forced publication or queue writes.

Same Master Plan and EVE6/79/159/170/156 updated with deployed facts, distinct access/network/venue/collector/processing categories and next actions. App same current-project/handoff/journal updated via2109 and final2112receipt. Historical741HTML labels are not a pending queue. Existing approved sources and the separate Spektrix20cohort are untouched. Focused verification88Python+14read-onlySQLcontrols and actual production/UI acceptance; test sandbox released. No routine collector CI dispatch.

## November 26 — EVE-156 shared venue research candidate (not deployed)

Feedzilla's existing Admin registration and ordinary refresh must share the same venue resolver, budget and address geocoder. Worker branch `codex/eve-156-shared-country-research` accepts versioned, locality-bound server permits instead of requiring the NYC collector label; validates US state and numbered street, GB street and postcode (including named streets without a house number), exact venue and locality, permitted evidence hosts, and conflict rejection. Deterministic GB extraction also accepts the new registered-country scope. The 13 focused country-address tests passed locally with exact source/test blobs 5fa64c41b0618b0ffd081851f7fe60ac6bb0665b and a6ee93e0993d9f3629d503ba929360506209ce06. Integrated worker tests are committed but not yet executed. Backend draft PR #2142 contains source-neutral context, locality/native-revision key, common permit, same existing gateway and preview/changed-event handoff candidates with rollback proofs. No live flag, budget, source, queue, publication, or migration changes; no paid search/model calls. Do not activate until exact cache/geocoder demand and publication continuation, legacy hold migration and new-registration location-only intake behavior, full US/GB tests and bounded production acceptance pass.

## November 26 — exact-blob worker regression

61/61 focused local Python tests passed (test_venue_research.py and test_venue_research_address.py). Exact blobs checked: venue_research.py 54b44c2eea2ffeaf82542c4aa66a8bf1d7110e32; venue_research_address.py 5fa64c41b0618b0ffd081851f7fe60ac6bb0665b; venue_evidence_selection.py 136451de43929d53b5a90c89c5e5bccc29094c81; tests 1a77dde12d67936e64160496287e9b011eb88481 and a6ee93e0993d9f3629d503ba929360506209ce06. Model/search/RPC are mocked in these tests. Production research and crawler-key reuse flags remain false; no paid call or new collector activation. This code is backwards compatible with the currently deployed NYC permit and legacy claim contract. Backend deployment and actual end-to-end acceptance are still separate gates.

## November 26 — EVE-156 owner-authorized production AI pilot

Production shared resolver infrastructure is live (DB migration 20261207070700; worker PR #603). Owner requested production AI activation. Runtime flags `VENUE_RESEARCH_ENABLED` and `VENUE_RESEARCH_USE_EXISTING_TAVILY_KEY` set true in the production collector project only; existing Tavily key stays server-only. Model `anthropic/claude-haiku-5.5` via Vercel AI Gateway, existing $1/month project budget unchanged. Use the existing three-minute venue phase and durable shared policy; admit at most 10 attempts/day (200000 input/5120 output token reservations), initially four exact current venue keys (US NYC + UK registered feed) and no automatic global admission. No historical holds reopened. Database remains disabled until fresh runtime deployment is verified. Prior same-SHA redeploy was skipped by the intentional ignore-build policy; use the repository's one-off [collector-build] release marker, not a permanent ignore-policy change. Actual research/geocoding/publication acceptance remains to be verified.

## November 26 — runtime OIDC activation correction

At 00:04 UTC Nov 27 the four approved pilot keys remained pending, no AI admission or spend; normal authenticated geocoder cron returned HTTP 200 and continued ordinary venue work. A rollback-only claim of Rich Mix succeeded, identifying that the DB admission was ready. The Vercel OIDC runtime contract provides x-vercel-oidc-token on the request, not the build-only environment value. Pass it explicitly after existing cron/operator authentication through run_pipeline, run_batch and configured; no process-global credential mutation or token logging. Log only research configuration readiness. No change to pilot keys, policy, schedules, budget or geocoder ordering. Actual provider/geocode/publication receipts remain required.
