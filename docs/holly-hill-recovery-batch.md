# Holly Hill recovery batch — November 8, 2026

Ben approved one batch for all 27 held source reviews, local publisher pacing
and La Vista/Bellevue recovery. This collector change provides five bounded
recovery paths: Elloree, SC Works Trident, Old Santee Canal Park, Orangeburg
County YMCA and Town of Santee. The existing MapSee/Udell inventory is retained.

The captured feeds produce 2, 57, 5, 1 and 1 candidates respectively. These 66
records are neither deduplicated nor published counts. Every required page or
detail must complete; a partial fetch cannot become a successful snapshot.
Public prices, waitlists, age conditions, registration and offsite addresses
survive the existing factual staging contract.

The Town of Santee adapter uses only the official calendar/feed/detail tuple.
Ben authorized its missing-address fallback to 33.484582, -80.48998, labeled
`Town of Santee — approximate town center`. It retains an empty street address,
explicit approximate narrative and provenance. A genuine published event
address takes precedence. Town Hall footer, mailing/registration addresses,
third-party hosts and online events do not establish a physical event venue.

Shared pacing uses an elapsed five-minute bounded robots cache and deadline-
aware wait admission. `publisher_pacing_deferred` distinguishes our scheduling
wait from a publisher HTTP rejection. The compatible backend must deploy before
this collector; deployment does not itself activate the five pending sources.
See `holly-hill-pacing-recovery.md` and `holly-hill-institution-recovery.md` for
the transport and institution contracts and their limitations.

`capture_holly_hill_batch.py --recovery-only` reads exactly the five reviewed
feeds through normal production guards, with no database writes. The original
full-batch audit including existing MapSee feeds remains available. The local
workspace's DNS cannot complete guarded live requests; use the normal Actions
audit and retain its receipt. Do not weaken the network guard for local access.

The referenced Bram conventions file and fallback shell conventions file were
absent at the reviewed base. Existing repository contracts and Ben's explicit
batch authorization govern this work; no substitute approval policy is invented.

Local integrated validation passed 770 tests plus 33 subtests and all five build-
selection checks. Release status at this checkpoint: ready for collector CI;
guarded live audit and production deployment remain pending. Backend compatibility
must be deployed before merging this collector release.
