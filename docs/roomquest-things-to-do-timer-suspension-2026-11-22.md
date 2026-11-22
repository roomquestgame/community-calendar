# Things-to-Do periodic timer suspension — November 22, 2026

Ben approved suspending the five-minute Things-to-Do timer after the worker/history review.

## Scope

Remove only the `/api/things-to-do-pilot` entry with schedule `*/5 * * * *` from
`vercel.json`'s `crons` array. The route, function configuration, authenticated
GET handler, one-use ticketed POST handler, coordinator and v2 implementation stay
available. Geocoding and timezone schedules are unchanged.

This is a periodic-wake suspension. It does not change activity policies, activate
v2, remove prepared frontier/history, cancel a running request or stop authorized
ticketed work. The reviewed state has expired v1, disabled v2 and no live page/
dispatch leases; retained v2 pages are prepared work under that disabled policy.

## Why the endpoint stays

Main #1045 / collector #255 added immediate work through private one-use tickets.
Main #1676 / collector #437 introduced v2 through the same endpoint. The old pilot
URL is therefore shared infrastructure. The idle recovery timer is the approved
scope; its successor and data are retained.

## Validation and deployment

The JSON parses and its complete structure differs only by the single cron entry.
No handler or collection logic changes, and no provider requests or production
worker invocations are used to test this configuration change. Routine GitHub
checks remain disabled under the owner policy.

Production effect requires a deployment with this configuration. Verify the exact
production source/alias and retained two-entry cron configuration, then observe
ordinary logs across the next five-minute boundary. The main EventQuest worker
suspension journal records the final deployment/readback receipt.

## Future resumption

If activity policy is deliberately reactivated, explicitly decide its recovery
schedule. Restoring the previous entry is a configuration change requiring a new
production deployment; do not enable it automatically while policy is inactive.

Reference: [Vercel cron maintenance](https://vercel.com/docs/schedules/cron-jobs/manage-cron-jobs).
