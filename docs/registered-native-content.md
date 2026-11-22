# Registered native calendar content v1

Prepared for EVE-150 on 21 November 2026. Release and live source acceptance are
separate from the local tests described here.

The separately negotiated HTML detail extension is described in
[registered-html-calendars.md](registered-html-calendars.md). It adds a checked
HTML registration receipt and actual per-event detail evidence; the original
JSON-feed contract below remains unchanged for WordPress and JSON-LD feeds.

## Purpose and scope

Direct registered WordPress Events Calendar and JSON-LD collections currently
lose descriptions after 2,000 characters and omit native event image candidates.
A WordPress collection with timed public events but no native venue objects also
fails before an Admin can review its individual venues. This protocol addresses
those three boundaries without granting publication or source access.

The backend authorizes the capability from the exact canonical registered source
and registration receipt. The collector checks the claim's JSON kind, supported
adapter, public HTTPS feed URL, and canonical `municipal_` source key: the prefix
plus the first 24 hex characters of `md5('feed_registration:' || feed_url)`.
`feed_registration` is the separate catalog origin and the hash input salt.
A positive capability with inconsistent identity fails; it does not fall
back to a legacy extraction path. Existing source approval, rights, collection,
claim, venue, curation and publication rules remain backend authorities.

No source-specific URL, venue, coordinate or permission is added by this change.
Robots, HTTP failures, same-endpoint pagination, date parsing, source deadlines,
staging deadlines, media leases and host pacing retain their existing behavior.

## Negotiated collection contract

Only an exact JSON integer `registered_native_content_version: 1` enables the new
collector behavior. Missing, boolean, string, zero and future-version values do
not enable it. The backend decorates the existing category-worker JSONB collect
claim after its normal authorized claim succeeds. Legacy fixed-table preview
claim signatures remain unchanged.

| Boundary | Native v1 contract |
|---|---|
| Source claim | Canonical `source_key`, exact `feed_url`, `kind=json`, `platform_adapter=wordpress` or `jsonld`, and integer capability 1 |
| Description | The native `description` field only; the existing sanitizer removes navigation, scripts and known layout shortcodes. Preserve at most 12,000 Unicode characters after sanitization. A 12,001-character result fails collection before any staging; no silent truncation. Missing/URL-only text stays empty. |
| Image | The native `image` field only, including bounded ImageObject/list/local-reference forms. Select at most the existing first five candidates; reject known tiny dimensions, empty/unresolved references, unsafe URLs and generic image paths. Missing or rejected images do not discard valid event facts. |
| Event identity | Existing stable normalized ID, existing occurrence times and event URL. Event URL must be public HTTPS on the same publisher host as the registered feed, using only the lowercase/single-leading-`www.` normalization described below. |
| Staging | Existing RPC name `community_collector_record_staged_events` with the new non-default fourth argument `p_registered_native_content_version: 1`, including an empty event array. All records are validated before the first batch. The legacy three-argument call is unchanged for noncapable sources. |
| Completion | Existing v3 preview receipt with `p_parser_capability=registered_native_content_v1`. Error receipts identify the protocol but never certify a completed snapshot. |

Every native record contains exactly this evidence object, with the record's own
values rather than substituted site or event identities:

```json
{
  "registered_native_content": {
    "version": 1,
    "source_key": "<canonical registered source key>",
    "feed_url": "<exact registered endpoint including selectors>",
    "adapter": "wordpress",
    "event_id": "<normalized stable row id>",
    "event_url": "<original normalized event URL>",
    "description_field": "description",
    "image_field": "image"
  },
  "image_extractor_version": "registered_native_content_v1"
}
```

`description_field` is null when sanitized text is empty. `image_field` is null
when no valid native candidate was selected. When a candidate is present, the
record additionally supplies `image_url`,
`image_provenance=registered_native_content_v1`, and
`image_evidence_url=<exact registered feed_url>`. The backend independently
validates the evidence and attaches full text/candidate metadata atomically to
the normal fact staging transaction. It supplies observation time.

The capability does not authorize a detail-page crawl, excerpt substitution,
generic Open Graph image, direct public image write, or broader calendar scope.

## Private venue review

Only the positively negotiated WordPress path skips the final collection-wide
`venue_extraction_unavailable` check when every native venue is blank. All
original event eligibility, status, time, pagination and transport checks remain.
JSON-LD's empty-venue behavior is unchanged.

The record still contains blank venue name/address and null latitude/longitude.
The collector never copies a source default into these fields. Existing backend
default matching requires a nonblank exact native venue name; a blank record
therefore cannot inherit default geometry. Normal classification holds a record
without verified coordinates, and normal publication still requires complete
actual venue evidence and an effective Include. A complete protected Admin
per-event correction can later make an eligible occurrence usable. Partial
overrides, unreviewed coordinates, paused/restricted sources and source-centre
guesses do not become publication authority. The existing stable event identity
and upsert preserve `override_*` fields on refresh.

The paired backend tests are responsible for the actual SQL approval/rights,
Hold/default, partial/full override, publication and refresh-preservation gates.
The Python tests establish that the collector leaves blank facts blank and does
not manufacture override fields; they do not emulate database authorization.

## Candidate media contract

Both the legacy media claim request and the dedicated media start/claim request
advertise integer `registered_native_content_version: 1`. The backend withholds
native media work from older callers. Returned native claims include:

- `source_key`, `feed_url`, `platform_adapter`, `kind=json` and exact integer version 1;
- `candidate_only=true`, the same-publisher `event_url`, and the staged `candidate_url`;
- `extraction_url` exactly equal to the registered `feed_url`.

Native event/feed host comparison matches the existing backend publisher-host
normalization: lowercase and remove one leading `www.` only. Original URLs and
the exact registered-feed source hash remain unchanged; sibling and other
subdomains do not become equivalent.

The worker checks those fields before any probe. Missing/invalid candidates never
cause a fallback page fetch. The existing media probe still checks public DNS at
every hop, redirect targets, allowed image MIME/signature, size/deadline and host
limits, and reads only the existing 4 KiB prefix. A successful result uses the
registered feed as evidence. Image availability remains optional to event facts.

For native v1 claims only, the probe also checks the current image path and query
against the existing cached publisher robots policy before each image GET,
including redirect destinations. This adds an auxiliary `robots.txt` lookup when
that host's policy is uncached. It uses the existing public-DNS/redirect policy,
128,000-byte robots limit and at most five seconds of network time, all within
the unchanged eight-second total image-probe budget. Policy and publisher pacing
run inside the existing per-host permit. Legacy image probes do not opt in.

Disallow, robots access denial and waits that cannot fit the existing one-hour
media-backoff bound produce no approved image and no page or alternate-host
fallback. Temporary policy/network/pacing failures use the existing closed media
defer outcomes and bounded numeric waits. Event facts remain intact. A cold or
slow policy lookup can consume the remaining probe budget; tests do not promise
an image will be verified on that attempt.

## Compatibility and deployment order

1. Review and deploy the companion backend contract first. It must include the
   explicit staging overload, claim/receipt capability, media negotiation and
   downgrade protection. The current app work reserves migration
   `20261206181000`; final release references belong in the workstream receipt.
2. Deploy this reviewed collector through its normal main-branch release path.
   No routine GitHub test dispatch or `ci:validate` label is required under the
   owner policy in `AGENTS.md`.
3. Use normal supported Admin Preview/Resume/review operations. A paused source
   remains paused until the authorized Admin process changes it. No source is
   automatically enabled by this protocol.
4. Verify actual staging/completion, protected venue/curation decisions, media
   validation and the resulting public events in both Events and Map.

Before the first v1 completion, noncapable legacy behavior remains available.
After a completed v1 enrichment, the backend excludes the source from legacy
fixed-shape claims and rejects older in-flight staging/success receipts that
could erase that enrichment. Do not bypass that guard or retry a rich payload
against an older backend. A missing deployment capability is not permission to
send the four-argument overload speculatively.

## Local evidence and limitations

The working base is collector main
`637136f98d7f112ac4dd3c1bf9dc6dbc6caadb1a`, preserving PR #411's JSON-LD reference
repair. A controlled original-versus-amended probe reproduced all five intended
changes: full WordPress/JSON-LD narratives, native image candidate, explicit
oversize failure, and private blank WordPress venue intake. The original failed
all five richer-contract expectations; the amended code passed all five.

The focused suite exercises real adapters and worker code with controlled
publisher bodies/RPCs. It checks malformed capability/provenance, all-record
validation before staging, empty snapshots, access errors, legacy behavior,
Unicode limits, optional images, candidate-only media and existing media guard
tests.

The pre-amendment local and independent peer runs each passed 302 tests and 34 subtests.
The subsequent native-only host-parity amendment adds eight cases; the focused
native module passes all 118 tests, including bare/`www.` equivalence, preserved
URL/source proof and sibling/subdomain rejection.
After the native image-policy amendment, the focused native/media modules pass
179 tests and two subtests. The cases include denial before GET, redirect denial,
exact path/query and host-permit placement, real cached robots parser/crawl-delay
behavior, temporary errors, numeric waits and the unchanged probe budget.
Independent review of the final combined code passes the full focused command
below: **325 tests and 34 subtests**. No production timing or access inference is
drawn from that controlled run.

Run:

```bash
python -m pytest tests/test_registered_native_content.py tests/test_wordpress_adapter.py tests/test_jsonld_family.py tests/test_publisher_evidence.py tests/test_preview_transport_errors.py tests/test_event_media.py tests/test_media_demand.py tests/test_description_shortcodes.py tests/test_description_url_only.py -q
```

The retained permitted Suffolk native response yields 11 local rows with blank
venue and null GEO, all 11 optional image candidates, and 470–1,059-character
descriptions. All three Willow rows retain their Workshop Barn statement. This
is extraction evidence, not a production stage/publication count. Conflicting
schedule prose and sold-out status remain Admin review matters; this patch does
not infer different times or venues.

No local test establishes live publisher latency, production SQL timing, actual
media bytes from these publishers, or Events/Map acceptance. Those require the
normal deployed receipts. Southern Maltings' Requests network failure and Lion's
separate free-label conflict are not repaired by this change.
