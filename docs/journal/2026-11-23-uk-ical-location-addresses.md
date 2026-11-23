# Keep the native UK street address in registered iCal intake

## Acceptance failure

After the ordinary PHCL preview, source 6218 had 47 exact publisher-default venue
matches with the reviewed point 51.54111, -0.1567256 and 3 protected per-event
venues. It still paused with `venue_location_unresolved`: the 47 matches had a
complete address inside `venue_name`, but their separate `venue_address` was
null. The registered-iCal verified-venue gate correctly requires an address as
well as the exact reviewed default name and point.

The direct registered-iCal worker already invokes
`ical_venue_address.extract_venue_addresses`. Its existing parser recognized US
street/city/state formats only. The PHCL native LOCATION is:

```
Primrose Hill Community Library, Primrose Hill Community Library, 11-16 Sharples Hall St, Primrose Hill, London, Greater London, NW1 8YN, United Kingdom
```

Source evidence: <https://www.phcl.org/events.ics> and the publisher's venue page
<https://www.phcl.org/locations/primrose-hill-community-library/>. The raw native
50-event feed captured on November 23 is the regression fixture. Source default
and individual point reviews were saved through Admin, not seeded by this code.

## Focused change

The existing registered-iCal extractor now retains a UK street suffix only when
the publisher LOCATION explicitly supplies:

- UK, GB, Great Britain or United Kingdom as its country component;
- a complete postcode accepted by the existing GB postcode-shape validator;
- exactly one numbered street, including a bounded house-number range;
- one to four locality components after that street.

The LOCATION must be shorter than the existing 160-character name boundary, so a
truncated name cannot become address evidence. URLs, online/virtual locations,
PO boxes, ambiguous multiple addresses, missing/foreign country, incomplete
postcodes and missing numbered streets are retained without new address fields.
Numbered venue prefixes and extra postcode evidence are also held: they can
hide a second address whose layout is outside the recognized street grammar.

The full original `venue_name` stays unchanged, preserving the Admin default's
exact name match. A specific existing address is never replaced. The parser
does not supply or change coordinates, category, time, timezone, UID, source
identity, description, permission, robots handling or a review decision. It
retains locality components in the address instead of guessing a postal town.
The existing US extractor remains unchanged after this additional bounded path.

This is publisher address evidence for the existing default/review gates. It is
not automatic GB geocoding: the native suffix may contain several locality and
country components, while a reviewed Geoapify query uses the existing separate
street, town and postcode inputs. No backend gate or provider threshold changes.

## Verification and expected Admin sequence

```sh
python -m pytest -q tests/test_registered_ical_uk_addresses.py tests/test_registered_ical_addresses.py tests/test_zero_duration_end.py
```

**61 tests pass**, including the exact 50-event PHCL snapshot. The comparison
against the existing behavior changes only 49 emitted address fields: 47 exact
default rows and 2 chess rows. The film's map URL remains untouched. All other
emitted fields and 50 unique event identities remain identical; extracted native
addresses add no coordinates. The test also proves repeat normalization is
idempotent, existing explicit addresses/points/decisions are preserved, and
negative address cases are rejected. Existing US address and equal-end tests
pass in the same focused run. Independent review identified the ambiguous-prefix
case; the guard and three targeted negative fixtures address it. `git diff
--check` passes. No routine CI is run.

This follows deployed collector PR #451 at
`2e8930101da138a44ad5ff6ef8fa840eed3571bf` and the independently deployed app
[PR #1753](https://github.com/roomquestgame/RoomQuestGame/pull/1753). It requires no
new database migration.

After the normal collector release, use an ordinary Admin preview. Preserve all
seven explicit PHCL timing Holds and the existing 50 occurrence IDs. A newly
populated native address changes the conservative venue-review fingerprint, so
the two chess occurrences 416599/416630 may need the normal verified-venue save
again against their latest staged facts. Preserve their reviewed point/evidence;
never relax the fingerprint to carry a stale review. The film 416618 map URL and
its protected review should remain unchanged. Root owns the supported Admin
reviews, source approval, and 43 public / 7 held acceptance check.

Independent review and parent review precede the normal PR merge and exact-Git
Vercel collector deployment. No production source change, publisher refetch,
geocoder retry, deployment or public acceptance is claimed by this local patch.
