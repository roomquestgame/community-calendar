# Publisher evidence and candidate-only photos

Iowa MyCountyParks, Bellevue Times and South Carolina Parks use the same active
image demand worker as Virginia's deployed v2 implementation. Virginia's parser
and image selector are unchanged. The worker still defaults to five concurrent
jobs, three per host, continuous refill, a 40-second budget and durable retries.
It probes publisher files and stores verified URLs; it never copies full images.

`publisher_event_details_v1` binds bounded raw cost, registration, audience and
meeting-place facts to the exact enrolled event URL. Native labels travel in
`publisher_categories`, including broad labels which do not determine activity.
MyCountyParks keeps its Event Summary and complete registration alternatives.
South Carolina preserves HTML narrative or the already-fetched JSON description,
factual headings and explicit topics. Its generic Open Graph image is excluded.

`publisher_event_candidates_v1` certifies that each collected occurrence was
checked for an event-specific photo, including honest no-photo and empty results.
Candidates must have provenance, an approved publisher URL and an extraction URL.
For Bellevue, the extraction URL is its first listing page; the occurrence URL
remains the card's identity. No Bellevue details or page-two fetches are added.

Staging, successful snapshot certification, publication, queue admission and
result recording all enforce these contracts. Source snapshot/image deadlines
still follow the coordinated effective 96-hour policy. Candidates are only
queued for actual current demand, permitted sources and eligible published
events. Changed/withdrawn evidence, holds and stale leases cannot attach photos.
The disabled legacy Udell backlog stays disabled. Existing Virginia-only workers
can claim Virginia candidates; the new capability handshake admits other sources.

Release: backend migration, production collector receipt, scoped record repair,
actual published-content/photo readback and installed-phone acceptance must be
reported separately. Code or a green workflow alone is not production acceptance.

## Optional facts and event holds

Use `optional_description` after validating the occurrence. A missing
description produces a warning and an empty field. When a trusted feed
already provides a summary, keep it if an optional detail page supplies
no additional prose. Independence Library, Unleash Council Bluffs, Think
Iowa City and Clarksville Tourism use this policy. Preserve descriptions
that the publisher provides and evaluate any access or status evidence
before accepting the occurrence.

Council Bluffs Public Library, Mason City, Experience Waterloo, Discover
Halifax, the reviewed ChamberMaster feeds and MyCountyParks also retain
verified occurrences with missing prose. Existing end-time evidence stays
optional. A missing narrative still matters when it supplies the actual
session schedule, as at Cooper's Landing, D&G Outdoors and The Prizery.

When a calendar listing, detail heading and structured export agree on the
event title, a disagreement in optional marketing copy can be reported as a
warning. Keep the corroborated title and drop the conflicting description
before classification. Date, time, public access, status and physical venue
conflicts still require evidence before publication. Keep an independently
confirmed venue correction scoped to the exact publisher and address pair.

Clarksville Tourism applies this policy to the poker and pool wording conflict.
The organizer's events page corroborates poker at 600 Virginia Avenue. The
Locable listing, event detail and export agree on 600, even though the organizer
profile on Locable gives 601. Each published occurrence uses the time actually
listed on the tourism calendar.
