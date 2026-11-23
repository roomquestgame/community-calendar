# National protocol and regional Wildlife fixtures

These are synthetic records using publisher field structures inspected on
22 November2026; they do not copy complete publisher event narratives.

Wildlife structure was verified against the BCN `/events/rss.xml` feed and
`/events/2026-11-23-nature-journaling-sharon-williamson-paxton-pits` detail.
Drupal supplies Event microdata, separate event date/time fields, an event Place,
native point/address, event summary/about and a dedicated hero image. RSS
`pubDate` uses a date or date range at synthetic noon, not the event clock.

OpenActive fixtures follow Better's public `session-series` and
`scheduled-sessions` feeds. Its parent contains descriptions and venues while
the scheduled occurrence references the parent's native identity and supplies
its own date/time/status. Both feeds use RPDE items/next/license, including
updates and tombstones. Bookwhen uses the same separate-stream shape; its
PartialSchedule must never be extrapolated. Tests synthesize pagination tails,
outages, late deletion, cursor escapes and transactional replay explicitly.

## Published Wildlife clock syntax

`wildlife-published-clocks.json` preserves the exact visible `Time` strings
from two official Lincolnshire event pages inspected on 23 November 2026:
`1pm to 3.30pm` and `1.30pm to 2.30pm`. The source URLs and visible dates are
recorded alongside them. Tests insert those strings into the existing
synthetic Drupal fixture; the fixture's venue remains synthetic test data.

The expected datetimes are explicit test controls derived from the visible
date and time, not a fresh capture of the publisher's hidden datetime
attributes. The web extraction did not expose raw attributes, and the local
guarded network reader could not resolve the publisher. This fixture proves
the clock-syntax regression and preserves datetime/date corroboration; it
does not establish a successful live Lincolnshire capture or explain the
Northumberland zero-output capture.

## Northumberland date-only template

`wildlife-nwt-date-clock.html` preserves the exact Event root attributes and
the reduced date/time DOM observed by the parent agent in the official
Northumberland event page on 23 November 2026:

https://www.nwt.org.uk/events/2026-11-25-wansbeck-natural-history-group-update-on-beavers-and-other-animals-wallington

The publisher's startDate is exactly `2026-11-25`. Its separate native
`field--name-field-event-time` field reads `19:00 - 20:15`; it does not use
BCN's `field--name-field-event-time-value` field. The date is not a midnight
or noon event time. The parser combines only this strict calendar date with
its independently published explicit clock in Europe/London.

The publisher Place metadata was observed as Middleton Village Hall,
Middleton, Morpeth, NE61 4RA, with point 55.160758, -1.908005. The fixture's
location wrapper is reduced to the existing verified field shape using those
values. Its title, summary and two About paragraphs are explicitly synthetic
controls, not a copy of the publisher narrative. The exact date/time snippets
and root attributes are unchanged.

Regression cases retain aware-datetime corroboration, reject conflicting
duplicate clock fields, incomplete clocks, RSS/date conflicts, date spans,
invalid points and ambiguous/nonexistent London wall times. They also verify
that complete native prose, evidence identity and coordinates survive.

## Lincolnshire primary event boundaries and reserve Place

The following reduced fixtures use structural DOM evidence observed on the
two canonical Lincolnshire pages on 23 November 2026. They are not raw HTTP
captures. Both original pages had exactly one full schema.org/Event root.

- `wildlife-linc-related-cards.html`:
  https://www.lincstrust.org.uk/events/2026-11-28-crochet-christmas-trees-workshop
- `wildlife-linc-reserve-place.html`:
  https://www.lincstrust.org.uk/events/2026-12-02-talk-boothby-wildland-nature-recovery-lincolnshire

The Crochet fixture preserves the main `node__header` / `node__content`
boundary, templated main date and clock ancestry, and all three observed
related-card wrappers, date values and clock strings. The related cards are
under the main article's `field--name-field-further-content`, an event-feed
paragraph, and `node__related__wrapper`; they do not declare Event itemtypes.
Broad descendant selectors consequently saw four startDate nodes and clocks.
Only this reviewed related-card boundary is excluded. A real duplicate main
date or clock, an unreviewed wrapper, or an additional Event root still holds.

The main and related location wrappers follow the observed ancestry and use
the observed Far Ings name/address/point. Related cards had an empty postal
address, their own images and no summary/about fields. Fixture titles,
description paragraphs, link labels and image filenames are synthetic controls.
Tests add deliberately conflicting related data to ensure it cannot supply the
main event's status, description, venue or image.

The reserve fixture preserves the observed Gibraltar Point Place outerHTML
(blank-line whitespace normalized), including its `node--type-reserve node--view-mode-address-string`
classes, native h3 name, PostalAddress reserve fields and both GPS values.
Its date/time fields are exact observed snippets; surrounding narrative/title
are synthetic controls. This variant requires one unambiguous native Place,
name, address and complete valid publisher point. It cannot borrow fields
from elsewhere in the Event or infer a venue.

A subsequent one-page live check found that Boothby's enclosing venue field
is `field--name-field-event-reserve`, under
`node__header > node__header_inner > node__event-location`, with a native
`Location:` label. The initial reduced fixture had copied the Place internals
but assumed the generic `event-location` outer field. It therefore did not
prove that this particular reserve event was reachable in the live parser.
The fixture now preserves the observed outer field too, and reproduces the
failure before the alias correction.

Only the observed reserve alias is added. The parser still requires exactly
one main Place across both wrappers, and the new wrapper must use the strict
reserve/address-string validation. Tests reject duplicate cross-wrapper
places, generic or unknown reserve shapes, and related-card reserve leakage.
