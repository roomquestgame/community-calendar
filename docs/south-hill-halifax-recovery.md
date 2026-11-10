# South Hill continuation: Discover Halifax coverage

## Observed gap and scope

The production Discover Halifax source (`discover_halifax_va`, source 5160)
completed its previous pull at 2026-11-08 03:36:11 UTC, which is November 7 at
10:36 p.m. in `America/New_York`. Its adapter only considered November 7–13.
The current directory advertises 61 listings, including later November and
December Woodbine events. This local seven-day filter excluded them before
detail retrieval. Two additional early listings had only a named venue or an
unnumbered trail address and were silently omitted before geocoding.

This change uses the existing shared 60-day horizon. It preserves the exact
registered source, ordinary HTML worker, publisher hosts, robots and pacing,
event evidence, shared geocoder and normal publication/media contracts. No
duplicate Woodbine registration, direct event insert or synthetic search demand
is introduced.

## Bounded collection and completeness

`discover_halifax.collect_chunk` enumerates and validates the entire advertised
directory, sorts its in-window identities, then reads at most six details in one
invocation. A prefix is explicitly incomplete and exposes no publishable events.
The durable checkpoint contains:

| Field | Meaning |
| --- | --- |
| `version`, `source_key` | Checkpoint format and exact registered publisher. |
| `started_at`, `window_start` | UTC start and fixed Eastern calendar-date window. |
| `manifest_hash`, `manifest_count` | Digest/count of sorted URL, title, date and clock tuples. |
| `cursor` | Number of enumerated detail records accounted for. |
| `events` | Normalized rows accumulated from completed detail work. |
| `diagnostics` | Bounded occurrence URL, disposition and explicit reason. |

Each continuation re-fetches and validates the listing. A changed manifest
invalidates accumulated facts and restarts the snapshot; a display-order change
does not. The fixed local-date anchor survives midnight. Checkpoints expire
after four hours and cannot exceed 900,000 UTF-8 JSON bytes, 200 directory cards
or 201 normalized occurrences (the reviewed Faire split adds one).

The caller must fence checkpoint reads/writes to the active category ticket and
source lease, persist revision changes atomically, and arrange the normal
demand-bound continuation. Partial work must not call the completed-preview
RPC or the publication RPC. Only a complete aggregate enters the existing
20-row staging batches and v3 certification. A failed detail request leaves the
previous durable chunk intact and retains normal error/backoff behavior.

`collect` remains a complete-only single-invocation audit path; it never calls a
prefix a healthy snapshot. Runtime checkpoint integration and its backend
migration are required together before activating this new collection behavior.

## Reviewed facts and owner decisions

### The Light, November 12

The official tourism [Still Life Drawing occurrence](https://gohalifaxva.com/directory/still-life-drawing-at-the-light/)
publishes November 12, 2026, 6–9 p.m., and only `The Light Spiritual Wellness`
in its address field. It links the venue website and carries the same telephone
number as the venue's [official contact page](https://www.thelightspiritualwellness.com/contact-3).
That page confirms 435 Main Street, South Boston, Virginia. The venue's own
[dated Breathe Friday page](https://www.thelightspiritualwellness.com/event-details/breathe-friday-fall-fusion)
also explicitly provides ZIP 24592.

The fallback is confined to the exact tourism URL, November 12 date, 6–9 p.m.
schedule, exact name-only address and reviewed linked website host. It supplies
`435 Main Street, South Boston, VA 24592` with no coordinates, so normal
geocoding remains authoritative. Any explicit publisher street is preserved;
unrecognized venues, changed schedules and relocation notices are not repaired
by this mapping.

### Earlier published times

Ben explicitly directed: **“With these types of situation pick the earlier
time.”** The reusable `publisher_schedule.earliest_published_time` accepts only
already parsed, timezone-aware times for the same independently matched local
event date. Listing/detail clock disagreement now selects the earlier instant
and records a warning. It does not infer a year, meridiem, timezone or missing
time, or reconcile different dates.

The [Woodbine Christmas Market](https://gohalifaxva.com/directory/woodbine-christmas-market/)
has November 15, 2026, 11 a.m.–5 p.m. in its structured listing/detail and
11 a.m. in the description. Its linked publisher flyer also advertises noon.
Under the owner's decision, the exact previous exclusion is removed and the
earlier 11 a.m. start is retained. Vendor-space products and their vendor fees
remain separate from public admission facts.

### November 21 Faire and Fantasy Ball

The [official tourism detail](https://gohalifaxva.com/directory/12646/) identifies
November 21, 2026, with two explicitly described sessions. The linked
[organizer ticket page](https://www.tickettailor.com/events/fbeconsultingandeventplanningllc/2345250)
and [organizer event page](https://www.fbeconsultingevents.com/event-details-registration/2nd-annual-wine-and-whimsy-festival)
corroborate the day and audience distinctions:

| Occurrence | Eastern schedule | Audience | Stable source ID suffix |
| --- | --- | --- | --- |
| Renaissance Faire | 11 a.m.–5 p.m. | All ages; children 10 and under free with a ticketed adult | `#faire-20261121` |
| Fantasy Ball | 7–11 p.m. | Adults 18 and older | `#fantasy-ball-20261121` |

Both retain the original tourism event URL and exact venue evidence. Each
receives its own schedule, source ID, session prose, explicit audience and
original registration link. Published early-bird prices are retained only when
present in the fetched narrative. The adult Ball does not inherit the Faire's
child-admission text. The split requires the exact reviewed date, venue and
current narrative session times; changed session evidence is held explicitly.

## Verification

Focused regressions cover a 30-record source spanning five chunks, no partial
publication, changed versus reordered manifests, interrupted detail fetches,
deadline reserves, fixed Eastern midnight windows, invalid/expired checkpoints,
the exact address repair and counterexamples, the owner's earlier-time rule,
explicit cancellation/address diagnostics, and separate Faire/Ball identities
and audiences. Fixtures use synthetic prose rather than copying publisher text.

Production collector deployment, checkpoint migration, genuine-demand refresh,
normal geocoding/media results and device visibility are distinct acceptance
steps; passing these offline tests does not claim those live outcomes.

## Shady Shack and release validation

`shady_shack.py` reads only the explicitly listed SpotApps event cards. The
owner's source-specific year decision assigns the current venue-local year;
an earlier month advances to next year only inside the shared 60-day window
crossing New Year. Explicit years prevail. Each assumption is recorded in
diagnostics separately from publisher facts. Weekly labels do not invent new
occurrences, and past, private, unresolved-time and offsite cards keep their
respective exclusions. The reviewed event venue is 183 Hendricks Mill Rd,
Bracey, VA 23919; normal geocoding determines coordinates.

Stable identities combine the publisher card ID and local occurrence date.
Only the observed SpotApps image shape (two hexadecimal path characters,
then thirty hexadecimal characters, then `w926`) becomes an image candidate;
normal image verification still applies. The captured fixture returns eight
occurrences and eight image candidates, not eight published events.

The reconciled November 10 candidate preserves the current civic collectors.
Its local affected-path run passed 588 tests and 26 subtests; five build-
selection checks, Python syntax, workflow structure and diff whitespace passed.
The local live probes stopped at `dns_unavailable` before any publisher HTTP
request, so they do not establish a publisher denial or successful collection.
The manual GitHub audit is the next release check. Its eleven endpoints retain
separate parsed, fetched-unparsed and blocked outcomes; it cannot activate a
source, create demand or publish events.
