# Descriptions on the linked event page

Ben clarified the scope: capture a description visibly present on the exact
page our event link opens. Do not follow another link to find one. Downtown
Norfolk, Reverb Lounge, and Sandler's single-show entries meet this condition;
their existing adapters read calendar cards without visiting those event pages.

## Implementation

The three reviewed adapters now expose strict event-page narrative extraction.
Downtown checks its canonical URL, title, and the scoped Details column.
Sandler checks canonical/OG identity, responsive title headings, and the
primary event-description column. Rockhouse checks canonical URL, title,
published date and show time before accepting its scoped description body.
No ticket, organizer, venue, or related-event links are followed.

`linked_event_descriptions.collect_chunk` reuses the existing complete calendar
facts, groups occurrences by their exact event URL, and reads at most six URLs
in each enrichment chunk. Existing Sandler detail requests needed for showtimes
remain inside the same source deadline and are reused within that invocation;
the six-URL limit is not a claim that those older factual requests disappear.

The private checkpoint contract already used for Discover Halifax stores the
completed prefix. Every continuation checks the current full factual manifest,
source identity, prior rows and four-hour window. Changed manifests restart.
A zero-progress deadline fails normally rather than spinning continuations.
Only a complete aggregate enters staging or receives a successful snapshot.
Skipped/failed requests therefore cannot erase old descriptions or omit events.
An explicitly empty description on a successfully matched page can remove old
prose. Title-only copy is empty; text still uses the shared 2,000-character cap.
The shared sanitizer also omits bare-URL-only descriptions. Fresh Sarpy Tourism
and Chesapeake Boards and Commissions payloads exposed that false-positive
case; their URLs are neither followed nor copied into prose. Useful text with
links and short actionable descriptions remain intact.

Backend capability advertising gates the new path. Until the matching migration
is available, the current listing behavior remains in effect. Collector code
does not change source rights, holds, normal refresh intervals or worker limits.

## Verification

307 relevant Python tests and ten subtests passed locally, including the new
chunk/worker tests and existing Halifax checkpoint and category-worker suites.
The engine tests exercise 13 URLs in 6/6/1 chunks, duplicate occurrences,
changed/expired/tampered checkpoints, transport/staging retries, deadline
handling, completed-only publication and Sandler response reuse.

Captured exact publisher pages produced 218 characters for Downtown's Blues
Dance, 726 for its Virginia Zoo Community Days, and 831 for Sandler's BEAT.
The strict Rockhouse helper passes the actual Admiral template capture; Reverb
uses that template but its raw page remains unavailable to the local audit.
Production refresh must establish the actual Reverb result before claiming
description coverage there.

Lauritzen's exact linked page does contain prose, but its raw HTML returned
HTTP 403 during inspection and no verified detail-body capture was available.
It is excluded from the active checkpoint profiles. Its collector is unchanged;
no guessed traversal or secondary-page enrichment was added. America's Pub
Quiz samples contain schedule/host/prize facts rather than comparable prose,
and no descriptions were invented for them.

The companion backend migrations repair queued publication and extend the
existing lease/token/CAS-bounded checkpoint contract to these exact sources.
Deploy through the normal current-head PR and live-schema rehearsal gates,
then validate source completion and compare staged/public prose separately.

## Publisher formatting follow-up

The fresh Doorways ICS snapshot contained Visual Composer layout shortcodes
that consumed the description limit before useful copy. The shared sanitizer
now removes only recognized layout/control shortcode names before HTML cleanup
and truncation, retaining enclosed text. Arbitrary brackets and unrecognized
shortcodes remain unchanged. This adds no requests or link traversal.

54 targeted tests pass, including the exact complete 1,922-character staged
Doorways layout section with explicitly synthetic prose beyond the old limit,
the generic Doorways ICS route, and Sarpy's URL-only feed route. The fixture is
not a raw publisher replay: normal local feed transport failed at DNS resolution.
A fresh production Doorways snapshot is required to verify recovered real prose.

The production follow-up completed at 22:53:26 UTC. Both original Doorways
occurrences now retain actual publisher narrative without shortcodes: Sip & Shop
describes the shops, complimentary wine and fundraising contribution; the VCU
Gala describes its ensembles, benefit purpose and ticket prices. Event URLs
remained unchanged. This receipt verifies staging, not public delivery.

## Omaha/Lincoln regional description bound

Francie & Finch's fresh collection reached staging but was rejected four times
with HTTP 400. The source-scoped database log identifies the error as
`HTML event description too long`. The regional collector still used the legacy
ICS parser's 12,000-character narrative, while all nine reviewed feeds in this
collector have a 2,000-character staging contract.

Keep the full parsed description for the reviewed venue/address rules, then
apply the shared narrative sanitizer at the final record boundary. This retains
identity, URL, dates, addresses and pins and adds no network requests. 51 targeted
tests pass, including Francie's long-description preview route and RiverFront
venue evidence occurring beyond the display cap. No retry deadline was reset;
normal production retry after deployment must verify Francie's real snapshot.
