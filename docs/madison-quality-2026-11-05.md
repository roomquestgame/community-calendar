# Madison publisher quality follow-up

Ben approved this bounded batch after confirming both Madison event cards on iPhone. Collector baseline: main `3e1e92c6`; backend enrollment is a companion guarded migration.

Madison-only extraction uses the current event's REST description/featured-image fields. One unambiguous same-publisher upload becomes an unverified candidate with canonical event evidence. Multiple images or off-publisher candidates produce no image. No image fetch or additional event-page request is added. Existing timezone confirmation, schedule, address and identity remain intact.

An explicit introductory `Join us ... on <month> <day>` conflict with the API calendar date adds a bounded schedule warning before the untouched publisher wording. It never silently corrects prose or shifts an event time. Current Basket Weaving needs this warning and has no source image; Aurora supplies one inline 300×300 JPEG. Structured API cost is retained as publisher evidence.

The candidate-only worker recognizes only this source's canonical event URLs and upload host/path. Staging and versioned completion use existing publisher-evidence contracts. Other WordPress sources keep their existing dispatch/output. Backend deployment must precede collector rollout because old databases do not enroll Madison in versioned completion.

Local validation: full provider workflow file set, 964 tests plus 33 subtests passed; meaningful added tests exercise the staged payload, exact completion RPC, source isolation, date-warning scope, bounded prose, ambiguous/missing images and off-host redirects. Fresh live REST captured two events; reviewed detail-page snapshots reproduce the 6–7 p.m. Central fallback. Direct local image verification was deferred by DNS resolution; no photo success is claimed. Native CI, guarded backend deployment, collector deployment and real-demand production verification remain required.
