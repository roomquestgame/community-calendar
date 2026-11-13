# Hurrdat event description cleanup — November 13, 2026

The expansion audit found one published Hurrdat Sports Bar event containing
Divi layout shortcodes instead of clean narrative. The exact linked
[Omaha trivia event page](https://hurrdatsportsbar.com/event/monthly-omaha-trivia-night-presented-by-hurrdat-one-3/)
has useful prose about the activity and its monthly schedule. No secondary
page is needed.

Staged row `239141` contains 1,931 characters, including both the five observed
Divi control names and actual enclosed prose. Removing those controls produces
604 characters of useful text. The captured staging fixture is not a raw
publisher API replay; the long-boundary test uses explicitly synthetic prose.

The actual WordPress route exposed a separate integration gap:
`preview_source` → `hurrdat_calendar` → `mapsee_adapter.parse_tribe` used its own
HTML cleanup. `parse_tribe(retain_description=True)` now calls the shared
description sanitizer at its existing 2,000-character output boundary. Invalid
description types still raise `invalid_wordpress_description`. The shared
helper removes only the observed `et_pb_section`, `et_pb_row`, `et_pb_column`,
`et_pb_text`, and `et_pb_code` wrappers, preserving enclosed prose. Unknown
shortcodes and ordinary brackets remain. This change adds no network request.

Focused verification passed 84 tests and 12 subtests across description
shortcodes, URL-only values, WordPress adapters, Nebraska venue sources and
market descriptions. The Hurrdat preview regression preserves event ID, title,
URL, start/end and venue fields while removing the layout markup. The existing
2,000/12,000-character sanitizer limits and embedded script/style cleanup are
covered. `git diff --check` also passed.

This follow-up does not activate the pending Downtown Norfolk, Reverb or
Sandler checkpoint capability, and does not apply the queued-publisher database
fix. Backend PR855 is merged and tested but its database deployment is blocked
by GitHub Actions billing. This collector release requires its own passing CI
and verified production deployment before a normal Hurrdat refresh is requested.
