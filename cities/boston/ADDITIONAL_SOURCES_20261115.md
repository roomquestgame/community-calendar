# Additional Boston venues — November 15, 2026 UTC

This consolidated batch resumes the previously unfinished venue work. The earlier
39 profiles are outside enrollment. A fresh production catalog check found no
matching source keys, feed URLs or publisher hosts for these 21 profiles.

## Captured source inventory

These counts are complete parser captures, not production-publication claims.
Descriptions are the complete native event text; short original descriptions are
not expanded with invented venue prose. Native access restrictions and explicit
session/holiday exceptions are preserved.

| Publisher | Captured occurrences | Description characters | Collection |
| --- | ---: | --- | --- |
| [Arnold Arboretum Public Programs](https://arboretum.harvard.edu/events/?ical=1) | 10 | 611–1191 | Bounded ordinary fetch |
| [Boston Harbor Now and Friends of the Harborwalk](https://www.bostonharbornow.org/events/) | 2 | 940–1813 | Complete-only checkpoint |
| [Brookline Arts Center](https://brooklineartscenter.org/workshops) | 9 | 319–600 | Bounded ordinary fetch |
| [The Burren](https://www.burren.com/music.html) | 105 | 9–4526 | Complete-only checkpoint |
| [Central Rock Gym Cambridge — BIPOC Climbers Meetup](https://centralrockgym.com/cambridge/events/bipoc-climbers-meetup/) | 2 | 1755–1755 | Bounded ordinary fetch |
| [Club Passim](https://www.passim.org/live-music/) | 61 | 258–7725 | Complete-only checkpoint |
| [Coolidge Corner Theatre](https://coolidge.org/) | 179 | 214–2275 | Complete-only checkpoint |
| [deCordova Sculpture Park and Museum](https://thetrustees.org/things-to-do/?_event_related_place=1730) | 7 | 639–2421 | Complete-only checkpoint |
| [Eliot School of Fine & Applied Arts](https://eliotschool.org/calendar) | 24 | 885–4209 | Complete-only checkpoint |
| [Harvard Museums of Science & Culture](https://hmsc.harvard.edu/programs/upcoming-programs/) | 5 | 602–3170 | Complete-only checkpoint |
| [Improv Asylum](https://calendar.improvasylum.com/) | 85 | 639–2085 | Complete-only checkpoint |
| [Laugh Boston](https://calendar.laughboston.com/) | 37 | 723–2180 | Complete-only checkpoint |
| [Lizard Lounge](https://lizardloungeclub.com/calendar/) | 30 | 332–4803 | Complete-only checkpoint |
| [Long Live Roxbury](https://www.longlivebeerworks.com/boston) | 3 | 362–362 | Complete-only checkpoint |
| [Museum of Science, Boston](https://www.mos.org/events) | 5 | 1731–8741 | Complete-only checkpoint |
| [New England Aquarium](https://www.neaq.org/engage/events-and-programs/) | 0 | No eligible public occurrence | Bounded ordinary fetch |
| [Parkour Generations Boston](https://pkgenboston.com/local-events) | 6 | 560–1842 | Complete-only checkpoint |
| [Peabody Essex Museum](https://www.pem.org/events) | 56 | 263–4294 | Complete-only checkpoint |
| [Rock Spot Climbing South Boston](https://climber.hellocapitan.com/rockspot/schedule/events/95/) | 136 | 579–3065 | Complete-only checkpoint |
| [Tracksmith Trackhouse Boston](https://www.tracksmith.com/pages/trackhouse) | 10 | 200–781 | Complete-only checkpoint |
| [The Trustees — Metro Boston Programs](https://thetrustees.org/program/metro-boston-programs/) | 2 | 641–756 | Complete-only checkpoint |

Total: **21 calendars / 774 eligible captured occurrences**.

## Existing coverage and content exclusions

- The exact Trustees December 19 Leland tree walk is already published through
  Boston Food Forest and is excluded from this additional cohort.
- The Passim Tall Heights page has only fee boilerplate; its Ticketmaster event
  `01006536E71D122A` is already public. No title-as-description substitute is used.
- The Aquarium currently has no eligible public occurrence after explicit sold-out
  and member-only restrictions are applied. A future eligible event can be collected.
- The existing four bookstore HTTP 403 holds are outside this batch and unchanged.

## Release contract

Deploy the consolidated collector first, then enroll all sources in the matching
application migration through one normal guarded Database workflow. The collector
uses existing source dispatch, guarded/paced transport, full-description validation,
complete-only checkpoints and shared publication/geocoding. No source-per-workflow
run or routine GitHub check is introduced. No mobile or website build is required.

Exact street provenance, native description hashes and eligibility decisions are
recorded in the additional source evidence. Production completion is recorded in
the companion RoomQuestGame batch report and PR release receipt.
