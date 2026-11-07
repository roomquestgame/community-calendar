# Iowa/Nebraska card quality cleanup

Approved follow-up to source batch #75/#76. Baseline f788f6ef6fca005136e53d105a796339822a6127; preserve EVE-41 calendar/access changes.

Trim every Waterloo publisher address component before joining. The Grout Museum publisher address contains a trailing street-space, which produced an extra space before the resolver delimiter. This corrects collection input without changing event identity or resetting geocoder requests/quotas. It does not prove the cause of earlier provider-submit failure, or supply a verified map point.

Use Surf Ballroom & Museum only when the Clear Lake source's own event URL has the exact surfballroom.com host and the complete 460 N/North Shore Drive, Clear Lake, IA 50428 address agrees. Official https://surfballroom.com/contact-us/ corroborates the name and full address. Keep explicit publisher venue names and raw meeting location; unrelated host/address combinations remain address-only. No event-title-to-venue inference or source-wide venue default.

Local pinned production-venv pytest: 1,627 passed and 37 subtests passed. Actual XML fixtures cover the venue correction and negative domain/address cases; padded Waterloo addresses retain the same event ID and start. git diff --check passed. Shared classifier/current public card repairs and guarded One Vision destination evidence are in the companion RoomQuestGame batch. No additional source activation or demand fabrication.

GitHub validation, merge, exact-source collector production deployment and live acceptance remain pending. Weis Mansion and Grout Museum points remain unresolved pending verified primary selected-point evidence.
