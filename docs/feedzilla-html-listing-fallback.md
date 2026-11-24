# EVE-159 — Generic HTML calendar coverage: What's On, explicit details, larger archives

November 23, 2026 · reviewed feature batch. This stage extends the existing
fully bounded HTML collector; it **does not** claim all pagination is solved,
nor that ten London sources have registered or published.

The current collector is unchanged in its event rights, source scope,
publisher robots/DNS/pacing checks, 35-second registration deadline and
all-or-nothing snapshot policy.

Changes:
- Accept **up to 8 explicitly linked, scope-preserving listing pages** (was
  3), while preserving the original **40-detail** cap. A ninth page, an
  ambiguous AJAX pager, a duplicate inventory or an unknown source scope
  still blocks registration and collection. This helps 4-page WordPress
  archives but is *not* multi-run pagination or a license to truncate.
- Recognize actual event detail URLs under `/whats-on/<slug>`,
  `/whatson/<slug>`, and `/live-events/<slug>` as well as the existing
  `/event/<slug>`; exclude nested category indexes and past navigation.
- When an individual detail has neither matching JSON-LD nor Event
  microdata, accept exactly **one** title/date/time/where set from publisher
  HTML labels with a verifiable physical London venue and strict
  `Europe/London` date/time/DST validation. No year assumptions, recurrence
  invention, dynamic API guessing or footer-only location substitutions.
  Other detail pages keep their existing technical hold.

Focused test fixtures:
- Explicit four-page `rel=next` and `rel=prev` archive, all pages visited
  before any detail fetch, retaining all four stable event identities.
- Wix/WordPress What's On detail pages with labeled dates, clock and London
  venue; older WordPress H2 heading matched to exact OG title with
  publisher-stamped footer address.
- Negative cases: multi-date range, variable time, private/virtual item,
  unlocated event, reversed end time, canonical conflicts, pagination beyond
  the cap, and source-scope conflicts.

**Follow-up capability:** Genuine generic **multi-run**, lease-fenced HTML
pagination (including JavaScript/AJAX widgets), larger detail inventories,
and page-specific publisher APIs are still needed for Horniman, Albany,
Omnibus, large Poplar pages, and future larger sources. Extend the existing
private fetch-checkpoint pathway for this source family rather than raising
unbounded request budgets. Wait to recheck original London registrations until
the specific relevant collector update is deployed; use Admin Feedzilla Intake
`#1217-1226`, never duplicate source registrations.

Official publisher references inspected:
- https://poplarunion.com/events/
- https://museumofthehome.org.uk/whats-on/victorian-britain-at-christmas/
- https://www.oxfordhouse.org.uk/event/friday-jazz-november-2/
- https://www.omnibus-clapham.org/whatson/julius-caesar-remixed
