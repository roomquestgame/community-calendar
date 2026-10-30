# ChamberMaster provider — Orangeburg pilot

Ben approved a dedicated ChamberMaster provider on October 29, 2026, managed as
one provider with multiple registered chamber sources, following the Localist
pattern. Orangeburg County Chamber is the first source. This is no longer a
request for an Orangeburg-only HTML collector or for credentialed ChamberMaster
account/CRM access.

## Verified public interface

- Public XML schedule: `https://business.orangeburgchamber.com/api/events`.
- A live HTTP 200 response contained 175 EventDisplay records; 18 timed records
  fall in the collector's next 60 days. All 18 have stable event IDs and links
  after this change. Zero supply precise coordinates or event venue addresses
  in the schedule response.
- Event-specific iCalendar exports provide dates and venue text. The November 5
  Farmers Market export identifies Claflin University outside the Jonas T.
  Kennedy Complex. The November 2 County Council export identifies the
  Administrative Center, 1437 Amelia Street, Orangeburg SC 29115.
- This public API is separate from the credentialed ChamberMaster/MemberZone
  account API. The previous assertion that Orangeburg API access required an
  account key was incorrect for this endpoint.

The actual upstream GrowthZone parser remains in use. The RoomQuest adapter now
preserves EventID and builds the public event URL correctly, appending EventID
only when absent. The year at the end of a slug is not an event ID. A regional
chamber has no default event venue. Pending/cancelled, all-day and unidentified
records are excluded from this timed preview; no all-day midnight is invented.

## Shared provider contract

`roomquest/chambermaster_sources.json` is the initial reviewed source manifest.
Future chambers are source rows under ChamberMaster, rather than separate
provider implementations. Each has an exact public API URL, publisher label,
timezone, enablement and health. Credentials must not be copied from any chamber.

The requested application integration must expose ChamberMaster as its own
provider entry and manage its sources together. Implement a private registry,
leases, per-source cadence/backoff and aggregate provider health like Localist,
through the existing app-admin authorization. Cached reads must not fetch every
chamber. Reuse the public XML adapter and the existing factual staging/venue
pipeline; preserve original source/event identity and geographic discovery.
Bound any per-event calendar export fetches and reuse verified venue/address
results. Never turn the chamber headquarters into every event's map location.

## Release state and remaining integration

The prepared collector adds `/api/chambermaster`, a one-source bounded claim,
20-detail/34-second full-snapshot limit, exact event/ICS identity matching,
source venue text and protected private staging. It rejects larger feeds with
an explicit failure instead of reporting a partial snapshot as complete.

The companion application migration adds XML transport, a separately managed
ChamberMaster source group, admin source save/provider controls, API health,
a token-gated claim gateway and a 96-claim UTC-day budget. The existing Data
source form routes GrowthZone additions into this group; source timezones still
require review. Approved sources have a 24-hour minimum automatic cadence;
explicit admin previews share the same daily budget. Generic collectors exclude
this group. No automatic collection Cron is added in this prepared release.

The provider switch and Orangeburg approval start disabled/pending. No original
cohort/geocoder/publication eligibility is extended. No migration, collector
deployment, source approval or live ingestion has occurred in this session.
Existing Localist and Ticketmaster remain separate. Community job 33 was read-only
verified inactive and remains unchanged.

## Validation

- 60 focused Python checks and 10 subtests pass, including gateway routing,
  calendar identity/time matching, limits, operator authentication and existing
  venue/geocoder behaviors.
- One pre-existing broader-suite test expects five preview Cron entries although
  current main intentionally has none. This batch does not restore those jobs.
- New registry and queue SQL executes in an isolated PostgreSQL fixture covering
  admin/token denial, disabled/idle behavior, claims, source pause and budget
  exhaustion. Full fresh-chain/PostGIS tests and production-schema rehearsal
  remain required before release.
- Protected publisher transport cannot run end-to-end in this workspace because
  direct DNS resolution is unavailable. Live XML and two iCalendar exports were
  fetched separately through the environment HTTP transport; the actual parser
  produced 18 future linked facts and zero source coordinates. No live geographic
  publication is established by this result.
