# Feed location evidence — November 21, 2026

This follow-up preserves street-address evidence for the existing Geocodio flow.
No coordinates are guessed and no new geocoder, schedule or database call is added.

- Nissi's exact official address string `1455 Coal Creek Dr. Lafayette, Co. 80026`
  is normalized to `1455 Coal Creek Dr., Lafayette, CO 80026`, with venue city
  Lafayette. Other strings/calendars are untouched.18 actual saved-response
  records retain the address and America/Denver schedule.
- Mt.Carmel's exact official calendar, with event-local Colorado Springs/Pueblo
  addresses in CO, now retains America/Denver alongside its UTC instant. This
  repairs lost timezone metadata that made public UI use the viewer timezone.
  Contradictory publisher offsets still fail; other cities/calendars are untouched.
- Shared postal-address extraction retains explicit non-US country fields,
  including WordPress/TEC venue.country. Existing US address cache keys remain
  unchanged. Froglife replay retains United Kingdom in all5 venue26896 events.

190 focused collector tests and14 subtests pass. Tests cover scoped addresses,
unknown/offsite values, country retention, unchanged US formatting, timezone
metadata, explicit-offset conflict and existing adapters/native evidence.

Deployment and Admin recollection are required before claiming production fixes.
Froglife remains subject to the existing geocoder's US-only result gate; preserving
country is necessary but does not itself resolve that integration limitation.
