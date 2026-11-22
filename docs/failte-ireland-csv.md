# Fáilte Ireland event CSV

This is a narrow, shared parser for the official Republic of Ireland event
dataset. Source intake still goes through the signed-in Admin registration
flow. This change creates no source rows, migrations, venue defaults or approval
decisions.

## Source and capability

| Property | Contract |
|---|---|
| Original endpoint | `https://failteireland.azure-api.net/opendata-api/v2/events/csv` |
| Official catalogue | `https://data.gov.ie/dataset/events` |
| Source key | `municipal_3e66b6dcc320f68038a12429` |
| Existing collector lane | `kind=json`, `platform_adapter=jsonld` |
| Required capability | Exact integer `registered_native_content_version: 1` |
| Registration receipt | `verified`, endpoint exactly as above, type `jsonld`, reason `registered_failte_csv_v1` |
| Timezone | `Europe/Dublin`; the Admin source should explicitly store this value |
| Scope | Explicit venue facts with a Republic of Ireland county; no Northern Ireland attribution |

The existing `jsonld` lane is a dispatch/capability identifier. The response is
parsed as CSV, never guessed to be JSON-LD. An added query, catalogue page, CKAN
mirror or other API URL does not enable this profile. The source hash, original
URL and capability must agree before any fetch. Registration needs at least one
eligible upcoming occurrence; an empty or stale response receives
`no_extractable_events` review.

Collection makes one guarded request to the original CSV endpoint. Normal
public-URL/DNS checks, robots policy, publisher pacing, HTTP error handling,
same-host redirect limits, byte limits and deadlines remain in force. It does
not fetch individual Contact or Booking URLs. A 401/403/quota error remains a
hold, with no mirror fallback or retry within the collection.

## Explicit date, time and venue facts

The complete response must contain exactly the 19 documented columns, in any
order:

```text
Name, Event Type, Description, Contact URL, Booking URL,
Contact Phone Number, Booking Phone Number, Venue Name, Address, County,
Latitude, Longitude, Is Free To Visit, Price, Start Date, End Date,
Start Time, End Time, Recurring Dates
```

The official historical mirror has one row per occurrence. Its `Recurring
Dates` column is `Yes`/`No`, not an RRULE or a list of dates. The collector never
expands that flag. The date and clock come from the separate published columns;
`T00:00:00` in a date field does not establish an event start time. Local clocks
use `Europe/Dublin` for the occurrence date, including daylight saving rules.
Ambiguous or nonexistent local clocks hold collection.

Missing start clocks are ineligible, with a diagnostic count. Missing end
clocks stay null. Equal start/end clocks also leave the end unknown and record
a warning. Conflicting dates, backwards clocks, malformed fields and unknown
recurrence values hold the whole capture. A multi-day envelope exceeding 24
hours, or a different end date without an end clock, is omitted as an unresolved
schedule; no continuous or daily sessions are invented. The existing 60-day
eligibility window is applied to explicit occurrences.

An explicit venue name, address and Republic county are required. County is
kept as address evidence and is never relabeled as a city. Country attribution
comes from this exact reviewed publisher profile plus the explicit Republic
county. Complete published coordinates are used as supplied; an absent pair
stays null for normal venue review. Partial, nonfinite or out-of-island pairs
hold collection. No source centre or guessed pin is substituted.

The normalized occurrence ID binds title, start/end, venue name/address/city,
coordinates, actual selected event URL and timezone. Exact duplicate rows are
deduplicated; conflicting records for one identity hold the capture. Normal
Admin venue and curation rules still decide whether an occurrence can publish.

## Native text and URL evidence

The complete sanitized `Description` is preserved up to the existing 12,000
Unicode-character native bound. Overflow holds collection rather than silently
truncating the publisher narrative. An empty native description stays empty.
The actual public HTTPS `Contact URL` is preferred; if it is absent or fails the
normal public-URL shape checks, the actual HTTPS `Booking URL` may be used.
HTTP URLs are not rewritten. The selected CSV field is recorded explicitly:

```json
{
  "version": 1,
  "source_key": "municipal_3e66b6dcc320f68038a12429",
  "feed_url": "https://failteireland.azure-api.net/opendata-api/v2/events/csv",
  "adapter": "jsonld",
  "event_id": "<normalized occurrence ID>",
  "event_url": "<actual selected Contact URL or Booking URL>",
  "description_field": "Description",
  "image_field": null,
  "evidence_url": "https://failteireland.azure-api.net/opendata-api/v2/events/csv",
  "extraction": "registered_failte_csv_v1",
  "event_url_field": "Contact URL"
}
```

`description_field` is null when the sanitized description is empty.
`event_url_field` can only be `Contact URL` or `Booking URL`. The original CSV,
not a contact page that was never fetched, is the evidence URL. The normal
native extractor version remains `registered_native_content_v1`. The validator
checks the exact proof, source identity and occurrence ID before staging.

The CSV contains no native image field. Image candidates, provenance and media
claims are always absent/rejected for this profile. The official catalogue
identifies the dataset as CC BY 4.0; source-rights acceptance remains part of
normal Admin review and is not inferred from registration success. This parser
does not extend the dataset licence to images on linked websites.

## Complete capture and staging

The parser accepts at most 3,000,000 UTF-8 bytes, 10,000 nonempty input rows and
5,000 eligible occurrences. It parses and validates the entire CSV before
returning records. A malformed final row, conflicting duplicate, exceeded bound
or elapsed deadline cannot certify an earlier valid prefix.

The existing worker's small incremental-snapshot optimization is optional. A
larger set falls back to complete native staging; it is not sliced to 500 rows.
The production-path test stages 600 synthetic occurrences in 30 native batches
and records an exact 600-row v3 completion. Empty collections use the existing
native empty staging acknowledgement. Normal collection/staging deadlines are
unchanged: the category worker has roughly 39 seconds and the legacy worker a
43-second cap. The 5,000-row bound is not a latency guarantee. A real capture
that cannot stage completely within the runtime fails closed and needs reviewed
durable continuation before it can be accepted; a longer backend writer lease
alone does not extend the worker runtime.

The companion backend must authorize the exact original-source receipt,
`registered_failte_csv_v1` proof, off-host public HTTPS Contact/Booking evidence,
and a maximum 5,000-row native count for this profile only. Generic native
same-host checks and limits must remain unchanged for other sources. Backend
writer freshness, rights, claim, venue and publication gates remain authorities.

## Fixtures and live acceptance

The official CKAN datastore response was captured on 22 November 2026 from:

`https://data.gov.ie/api/3/action/datastore_search?resource_id=61b9eab1-45a6-41be-9c4b-80496b544de0&limit=2000`

It contains 1,589 historical rows, with the latest end date 18 January 2025.
The reduced fixture serializes those published fields into CSV, removes CKAN's
`_id`, and replaces descriptions with synthetic text. It is schema evidence,
not a fresh response from the CSV endpoint. It yields zero eligible events in
the current collection window and does not pass current-event registration.

Synthetic tests cover upcoming dates, multiline/quoted CSV, explicit recurring
rows, missing clocks, daylight saving conflicts, venue facts, contact/booking
provenance, full descriptions, scope/capability guards, 600-row worker staging,
last-row failures, deadlines and bounds. They do not prove current publisher
availability or deployed database acceptance.

The publisher's live CSV was previously observed to return a daily bandwidth
quota denial. No repeat request was made during that known hold. A fresh
successful response after the reset, the paired backend release, and normal
Admin registration/preview receipts are still required for live acceptance.
