# Redacted forward-geocoder failure evidence — EVE-150

November 22 follow-up: [private US candidate review](geocoder-private-candidate-20261122.md)
adds a bounded, unaccepted candidate only to the authenticated database payload.
Console diagnostics remain flags only. The release/handoff below describes the
original flags-only rollout; the linked follow-up defines the narrow exception.

The first actual Admin-reviewed ADC Theatre request completed as `ambiguous`
without coordinates. The existing collector used that same outcome for an HTTP
400/422 rejection and every unusable HTTP-success response. Its receipt therefore
could not establish whether the provider rejected the request or returned an
empty, malformed, or mismatched result. The historical receipt cannot be
reconstructed by this change.

## Bounded additive diagnostics

The collector retains existing failure outcomes and adds `diagnostic` to its
ordinary, country/query-bound `fail` payload. It also emits the sanitized
flags (excluding any private candidate) in a structured failure log with validated queue/request identifiers.
The companion database repair independently allowlists this evidence for Admin.

| Observation | Existing outcome | Diagnostic cause |
| --- | --- | --- |
| HTTP 400 or 422 | `ambiguous` | `http_rejected`, actual status |
| Empty result array | `ambiguous` | `empty_results` |
| Wrong result container, candidate shape, or excessive count | `ambiguous` | `invalid_results` |
| Invalid coordinates, score, or component object | `ambiguous` | `invalid_result` |
| Country, supported precision, or address does not pass existing verification | `ambiguous` | `result_mismatch` |
| Malformed JSON or oversized success body | `invalid_response` | `invalid_json` or `response_too_large` |
| Network error or refused redirect | `provider_error` | `transport_error` or `redirect_refused` |

Authentication, GB access-rejection, rate-limit, and server-error mappings remain
unchanged. No result-acceptance function, country/query guard, precision policy,
reservation, quota, attempt count, backoff, request timeout, or worker deadline is
relaxed. An unusable result now carries its cause in `GeocodeFailure`; the worker
still records exactly one ordinary failure, without retrying the HTTP request.

Evidence accepts only version 1; a fixed cause; an observed integer HTTP status
between 100 and 599; an integer result count clipped to 3 (meaning three or more);
fixed error classes; and boolean shape, field-presence, validity, and match flags.
Unknown keys, invalid enums, and wrong types are dropped before RPC or logging.
No raw provider body, request URL, API key, address, venue name, or exception
text is copied into diagnostics. Coordinates are excluded from console logs;
the later private US candidate exception is bounded by the linked follow-up. The pre-existing exact query in the
authenticated lifecycle payload is unchanged and is not added to logs.

An HTTP error body is read once, capped at 4,097 bytes. Only a complete body of
at most 4,096 bytes can supply a JSON `error` string for classification; the body
is then discarded. Recognized documented phrases map to `missing_locality`,
`usage_limit`, or `key_permission`. `uk_access_denied` requires an explicit
provider statement that the account lacks UK data access. Unknown messages stay
`unclassified`; HTTP status alone never establishes the account's plan, terms,
or UK entitlement. No account configuration or subscription action is performed.

## Contract and release

The SQL companion sanitizes the same keys and stores `evidence.diagnostic`,
without changing `last_error`, outcomes, or backoff. Its separate exact reviewed
GB retry action preserves attempts and the existing due time, and requires the
current eligible review with no active lease or request. This collector neither
invokes that action nor changes queue state outside its existing lifecycle.

Older backends ignore the additive diagnostic field while preserving their
normal failure processing; the redacted runtime log still carries the evidence.
Verify both companion releases before a later owner-authorized Admin retry.
The ordinary minute scheduler must handle that retry after the existing backoff.
No provider request or live retry was made while preparing this change.

Focused command: `python -m unittest tests.test_forward_geocoder`.
The 61 tests include existing US/GB matching, reservations, quotas, deadlines and
authentication, plus bounded error reads, HTTP/result distinctions, whitelist
classification, redaction, malformed diagnostic values, unchanged accepted
precision, and identity-bound failure forwarding. All transport and database
operations are mocked. `git diff --check` passes. No broad provider suite or
routine GitHub test workflow is required.

## Primary provider references

- [Geocodio API errors](https://www.geocod.io/docs/#errors): HTTP 200 can contain no results; HTTP 422 reports an unprocessable input; HTTP 403 has several possible access causes.
- [API key permissions](https://www.geocod.io/docs/#permissions): the documented permission-error message.
- [403 troubleshooting](https://www.geocod.io/guides/403-forbidden): usage, key permissions, and invalid-key possibilities must be distinguished from the actual response.
- [UK account-access error notice](https://www.geocod.io/updates/2026-06-10-changes-to-pay-as-you-go-plan): supports only the explicit UK-denial classification, not an assumption about the current account.

Endpoint v2 and explicit `country=GB` remain correct. This diagnostic release is
not a successful geocode, a published event, or additional Cambridge coverage.

