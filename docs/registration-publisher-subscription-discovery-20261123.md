# Reusable registration: first-party subscriptions inside calendar UI

**Scope:** EventQuest feed-registration collector, November 23, 2026.
**Owner approval:** improve normal Admin registration so public calendar URLs auto-discover feed endpoints without unnecessary human review. Use the existing leased registration dispatcher, robots-aware transport, and normal child registration. This change does not register, approve, or publish sources by itself.

## Verified publisher evidence

- Farmville Area Chamber original page `https://www.farmvilleareachamber.org/upcoming-events` links to its one full `/events` page. That page publishes a Google Calendar subscription URL with `cid=webcal://www.farmvilleareachamber.org/calendar.ics`. The original `https://www.farmvilleareachamber.org/calendar.ics` returned a real VCALENDAR, 243 VEVENT entries (some far beyond EventQuest's discovery window); normal collector must apply time bounds and event validity. The Google URL is only a subscription *wrapper*, not the publisher feed.
- LCVA `https://lcva.longwood.edu/events-calendar/` exposes a first-party TEC month iCalendar link `/events/month/?shortcode=c5cb6fd5&ical=1` and a Google calendar subscription. The observed month export contained just **three past VEVENTs** (at time of inspection, November 23). Its generic TEC JSON collection reported zero upcoming events. Do **not** silently treat that month export as an evergreen full collection.

## Implementation

- `CalendarLinks` identifies exact Google Calendar `/calendar/render?cid=webcal://...` subscription links on two known Google hostnames, decodes the original publisher feed only, then checks public URL, same hostname, no credentials or individual-event export identity.
- Prefer explicit direct first-party calendar exports over Google/Outlook-like wrapper links. Never let a Google wrapper silently replace a filtered or foreign-host calendar; multiple remaining candidates stay reviewable.
- Bounded generic calendar navigation from an unfiltered publisher `/upcoming-events` to exactly one directly linked `/events` page. The registration worker fetches that new page through the same guarded transport, independently checks its calendar evidence, and returns the original/child endpoint through normal registration callbacks. No guess based on mere domain similarity, no extra network call if direct feed is already available.
- A direct `/month/`, `/week/` or `/day/` ICS export is explicitly **not** accepted as evidence of a complete recurring feed. It stays `calendar_period_scope_unverified` unless an independent full source is proven.
- No modifications to workers, databases, scheduler, permission controls, user-facing UI, events, geocoding, categories or overlays.

## Focused tests and acceptance

`tests/test_registration_publisher_subscriptions.py` verifies Farmville's wrapped-ICS lookup, alternate Google hostname, direct-feed priority, foreign-host / credentials / single-occurrence rejection, multiple candidate ambiguity, filtered-scope hold, LCVA's month-only hold, and a two-page registration handoff with robots-aware fetch assertions.

Actual deployment acceptance separately requires: focused tests executed in an isolated collector environment; Vercel build READY on exact commit; rechecking a supported original registration through authorized Admin workflow; original source-to-child URL linkage; validated ICS events within active window and correctly placed venues; public EventQuest Events and Map confirmation; no publisher denial or duplicate records.

This shared improvement does **not** solve HTML event details lacking JSON-LD, JS-only pagination, Rockhouse scope ambiguity, conflicting Event references, or ticket-provider pagination. Keep these in actionable review rather than guessing event facts.

No routine GitHub CI should be introduced or dispatched automatically.
