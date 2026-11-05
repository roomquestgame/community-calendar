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
